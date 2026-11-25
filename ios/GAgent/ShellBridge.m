// In-process POSIX shell for code_run: ios_system (v3.0.5) running dash.
//
// iOS cannot start child processes, so every command is a thread of this app. The app does not
// link ios_system: the framework exports its own exit, abort, fork, chdir and printf, and linking
// would make them replace libc's for the whole app. It is loaded with dlopen instead, which keeps
// those symbols to the command frameworks that are built against them.
#import <Foundation/Foundation.h>
#include <dlfcn.h>
#include <pthread.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

extern char **environ;

// ios_system gives each command a small id ("pid") and keeps the thread running it in a table.
#define COMMAND_ID_LIMIT 128                       // IOS_MAX_THREADS in ios_system
#define NOT_STARTED ((pthread_t)-1)                // id handed out, thread not created yet
#define DASH_SKIP_TO_END 4                         // SKIPFUNC in dash: what `return` sets

static const char *SESSION = "ga_code_run";
// ios_system installs process-wide handlers for these while a command runs.
static const int GUARDED_SIGNALS[] = {SIGSEGV, SIGBUS, SIGPIPE, SIGINT, SIGWINCH};
#define GUARDED_SIGNAL_COUNT (sizeof(GUARDED_SIGNALS) / sizeof(GUARDED_SIGNALS[0]))

static struct {
    void (*initializeEnvironment)(void);
    void (*switchSession)(const void *);
    void (*closeSession)(const void *);
    void (*setContext)(const void *);
    void (*setStreams)(FILE *, FILE *, FILE *);
    void (*settty)(FILE *);
    void (*setDirectoryURL)(NSURL *);
    pid_t (*fork)(void);
    int (*system)(const char *);
    pthread_t (*getThreadId)(pid_t);
    int *dashLimit;
    const char *dashPath;
} shell;

static const char *load_error;
static _Atomic(bool) busy;
static _Atomic(bool) cancelled;
static _Atomic(pid_t) script_identifier;           // the id of the dash thread of the current run

typedef struct {
    const char *command;
    const char *directory;
    FILE *input;
    FILE *output;
    int status;
} ShellRun;

// initializeEnvironment() exports settings for a terminal app (SSL_CERT_FILE, PYTHONHOME, XDG_*,
// colours ...) into the process environment, where the embedded Python would pick them up too.
// Keep only what the commands need.
static void initialize_environment(void) {
    NSMutableSet<NSString *> *before = [NSMutableSet set];
    for (char **entry = environ; *entry; entry++) {
        [before addObject:[@(*entry) componentsSeparatedByString:@"="].firstObject];
    }
    shell.initializeEnvironment();
    NSMutableArray<NSString *> *added = [NSMutableArray array];
    for (char **entry = environ; *entry; entry++) {
        NSString *name = [@(*entry) componentsSeparatedByString:@"="].firstObject;
        if (![before containsObject:name] && ![@[@"APPDIR", @"TMPDIR"] containsObject:name]) {
            [added addObject:name];
        }
    }
    for (NSString *name in added) unsetenv(name.UTF8String);
    setenv("TERM", "dumb", 1);
    // ios_system logs with NSLog throughout. When NSLog also writes to stderr, a command cancelled
    // inside that write dies holding CoreFoundation's log lock and aborts the app in its cleanup.
    setenv("CFLOG_FORCE_DISABLE_STDERR", "1", 1);
}

static void load_shell(void) {
    NSBundle *bundle = NSBundle.mainBundle;
    NSString *frameworks = bundle.privateFrameworksPath;
    void *handle = dlopen([frameworks stringByAppendingPathComponent:@"ios_system.framework/ios_system"].fileSystemRepresentation,
                          RTLD_NOW | RTLD_LOCAL);
    NSString *dash = [frameworks stringByAppendingPathComponent:@"dash.framework/dash"];
    if (!handle || ![NSFileManager.defaultManager fileExistsAtPath:dash]
        || ![bundle pathForResource:@"commandDictionary" ofType:@"plist"]) {
        load_error = "this build has no built-in shell";
        return;
    }
    struct { void **target; const char *name; } symbols[] = {
        {(void **)&shell.initializeEnvironment, "initializeEnvironment"},
        {(void **)&shell.switchSession, "ios_switchSession"},
        {(void **)&shell.closeSession, "ios_closeSession"},
        {(void **)&shell.setContext, "ios_setContext"},
        {(void **)&shell.setStreams, "ios_setStreams"},
        {(void **)&shell.settty, "ios_settty"},
        {(void **)&shell.setDirectoryURL, "ios_setDirectoryURL"},
        {(void **)&shell.fork, "ios_fork"},
        {(void **)&shell.system, "ios_system"},
        {(void **)&shell.getThreadId, "ios_getThreadId"},
        {(void **)&shell.dashLimit, "numDashCommands"},
    };
    for (size_t index = 0; index < sizeof(symbols) / sizeof(symbols[0]); index++) {
        *symbols[index].target = dlsym(handle, symbols[index].name);
        if (!*symbols[index].target) load_error = "the built-in shell does not match this app";
    }
    if (load_error) return;
    shell.dashPath = strdup(dash.fileSystemRepresentation);
    // dash keeps its state in globals, so ios_system loads a framework copy (dashA, dashB ...) for
    // each dash it starts, up to this limit. The app ships one copy.
    *shell.dashLimit = 1;
    initialize_environment();
}

// dash is stopped the way its own `return` works: it checks evalskip between commands and then
// leaves the script through its normal exit. It must not be cancelled like other commands: it
// would die inside ios_system holding the id lock, and its SIGINT path kills the process.
//
// ios_system loads dash for each script and unloads it afterwards, which is what resets dash's
// global state. So the framework is only looked up here, never kept loaded.
static void ask_dash_to_stop(void) {
    void *dash = dlopen(shell.dashPath, RTLD_NOLOAD | RTLD_NOW);
    if (!dash) return;
    int *skip = dlsym(dash, "evalskip");
    if (skip) *skip = DASH_SKIP_TO_END;
    dlclose(dash);
}

// Counts the commands that still have a thread, optionally asking them to stop. pthread_cancel
// acts at a command's next blocking system call.
static int live_commands(bool cancel) {
    int count = 0;
    if (cancel) ask_dash_to_stop();
    for (pid_t identifier = 1; identifier < COMMAND_ID_LIMIT; identifier++) {
        pthread_t thread = shell.getThreadId(identifier);
        if (thread == 0 || thread == NOT_STARTED) continue;
        count++;
        if (cancel && identifier != atomic_load(&script_identifier)) pthread_cancel(thread);
    }
    return count;
}

// Runs on a thread of its own: ios_system keeps its session and streams in thread-local storage.
static void *run_command(void *context) {
    ShellRun *run = context;
    @autoreleasepool {
        shell.switchSession(SESSION);
        shell.setContext(SESSION);
        shell.setStreams(run->input, run->output, run->output);
        shell.settty(NULL);
        shell.setDirectoryURL([NSURL fileURLWithPath:@(run->directory) isDirectory:YES]);
        atomic_store(&script_identifier, shell.fork());   // ios_system expects an id for each command
        run->status = shell.system(run->command);   // returns when the command has ended
        shell.closeSession(SESSION);
    }
    return NULL;
}

// Runs one ios_system command line in `directory`, writing its stdout and stderr to output_fd.
// Returns the exit status once the command and everything it started have ended. On failure
// returns -1 and sets *error. The process working directory is left changed.
int ga_shell_run(const char *command, const char *directory, int output_fd, const char **error) {
    static dispatch_once_t once;
    dispatch_once(&once, ^{ load_shell(); });
    *error = load_error;
    if (load_error) return -1;
    bool idle = false;
    if (!atomic_compare_exchange_strong(&busy, &idle, true)) {
        *error = "another shell command is still running";
        return -1;
    }
    ShellRun run = {command, directory, fopen("/dev/null", "r"), NULL, -1};
    int descriptor = dup(output_fd);
    if (descriptor >= 0) run.output = fdopen(descriptor, "w");
    pthread_t thread;
    struct sigaction saved[GUARDED_SIGNAL_COUNT];
    for (size_t index = 0; index < GUARDED_SIGNAL_COUNT; index++) sigaction(GUARDED_SIGNALS[index], NULL, &saved[index]);
    atomic_store(&cancelled, false);
    atomic_store(&script_identifier, 0);
    if (run.output) setvbuf(run.output, NULL, _IOLBF, 0);
    if (!run.input || !run.output) {
        *error = "could not open the shell streams";
    } else if (pthread_create(&thread, NULL, run_command, &run) != 0) {
        *error = "could not start the shell thread";
    } else {
        pthread_join(thread, NULL);
        // Commands the script left behind (`cmd &`, pipeline members) still use the streams.
        while (live_commands(atomic_load(&cancelled)) > 0) usleep(20000);
    }
    for (size_t index = 0; index < GUARDED_SIGNAL_COUNT; index++) sigaction(GUARDED_SIGNALS[index], &saved[index], NULL);
    if (run.input) fclose(run.input);
    if (run.output) fclose(run.output); else if (descriptor >= 0) close(descriptor);
    atomic_store(&busy, false);
    return *error ? -1 : run.status;
}

// Asks the running script, if any, and every command it started to stop. Call it repeatedly until
// ga_shell_run returns: dash clears the request when a function or sourced file ends, and a
// command that never reaches a blocking system call cannot be stopped.
void ga_shell_cancel(void) {
    if (!atomic_load(&busy)) return;
    atomic_store(&cancelled, true);
    live_commands(true);
}
