// Simulator check of GAgent/ShellBridge.m against the real ios_system and dash binaries.
// Built and run by shell_harness.sh; it is not part of run_all.py because it needs a simulator.
#import <Foundation/Foundation.h>
#include <fcntl.h>
#include <pthread.h>
#include <signal.h>
#include <unistd.h>

int ga_shell_run(const char *command, const char *directory, int output_fd, const char **error);
void ga_shell_cancel(void);

// The simulator shares the Mac's /etc/profile, which dash reads; a phone has no such file.
static NSString *const SIMULATOR_NOISE = @"/usr/libexec/path_helper: command not found\n";
static const int ANY_STATUS = -99;
static const double GIVE_UP_SECONDS = 15;

static NSString *workDirectory;
static int failures;

typedef struct { int descriptor; NSMutableData *data; } Reader;

static void *read_all(void *context) {
    Reader *reader = context;
    char buffer[4096];
    ssize_t count;
    while ((count = read(reader->descriptor, buffer, sizeof buffer)) > 0) [reader->data appendBytes:buffer length:count];
    return NULL;
}

typedef struct { const char *command; int descriptor; int status; const char *error; volatile bool done; } Call;

static void *call_shell(void *context) {
    Call *call = context;
    call->status = ga_shell_run(call->command, workDirectory.UTF8String, call->descriptor, &call->error);
    call->done = true;
    return NULL;
}

// Runs a script, asking it to stop every 0.1 s once cancelAfter seconds have passed (0 = never).
// Passes when it ended with the expected status and output; nil output accepts any.
static void check(NSString *name, NSString *script, int expectedStatus, NSString *expectedOutput, double cancelAfter) {
    NSString *path = [workDirectory stringByAppendingPathComponent:@"script.sh"];
    [script writeToFile:path atomically:YES encoding:NSUTF8StringEncoding error:NULL];
    int ends[2];
    pipe(ends);
    Reader reader = {ends[0], [NSMutableData data]};
    Call *call = calloc(1, sizeof(Call));   // leaked on purpose when the script never ends
    call->command = strdup([NSString stringWithFormat:@"dash \"%@\"", path].UTF8String);
    call->descriptor = ends[1];
    pthread_t readerThread, callThread;
    pthread_create(&readerThread, NULL, read_all, &reader);
    NSDate *start = [NSDate date];
    pthread_create(&callThread, NULL, call_shell, call);
    while (!call->done && -start.timeIntervalSinceNow < GIVE_UP_SECONDS) {
        if (cancelAfter > 0 && -start.timeIntervalSinceNow > cancelAfter) ga_shell_cancel();
        usleep(100000);
    }
    double seconds = -start.timeIntervalSinceNow;
    if (!call->done) {
        printf("FAIL %-20s still running after %.0f s; stopping here\n", name.UTF8String, seconds);
        exit(3);
    }
    pthread_join(callThread, NULL);
    close(ends[1]);
    pthread_join(readerThread, NULL);
    close(ends[0]);
    NSString *output = [[NSString alloc] initWithData:reader.data encoding:NSUTF8StringEncoding] ?: @"<not utf-8>";
    output = [output stringByReplacingOccurrencesOfString:SIMULATOR_NOISE withString:@""];
    if (call->error) output = [NSString stringWithFormat:@"<error: %s>", call->error];
    BOOL pass = !call->error && (expectedStatus == ANY_STATUS || call->status == expectedStatus)
        && (expectedOutput == nil || [output isEqualToString:expectedOutput]);
    if (!pass) failures++;
    printf("%s %-20s status=%d %.1fs output=%s\n", pass ? "PASS" : "FAIL", name.UTF8String, call->status, seconds,
           [output stringByReplacingOccurrencesOfString:@"\n" withString:@"\\n"].UTF8String);
}

static void expect(NSString *name, BOOL condition) {
    if (!condition) failures++;
    printf("%s %s\n", condition ? "PASS" : "FAIL", name.UTF8String);
}

int main(void) {
    @autoreleasepool {
        setvbuf(stdout, NULL, _IONBF, 0);
        NSFileManager *files = NSFileManager.defaultManager;
        workDirectory = [NSTemporaryDirectory() stringByAppendingPathComponent:@"ga shell harness"];
        [files removeItemAtPath:workDirectory error:NULL];
        [files createDirectoryAtPath:workDirectory withIntermediateDirectories:YES attributes:nil error:NULL];
        workDirectory = workDirectory.stringByResolvingSymlinksInPath;
        NSString *here = [workDirectory stringByAppendingString:@"\n"];
        signal(SIGPIPE, SIG_IGN);   // as the embedded Python does

        check(@"echo", @"echo hello\n", 0, @"hello\n", 0);
        // Loading the shell must leave the process usable for the rest of the app.
        struct sigaction pipeAction, faultAction;
        sigaction(SIGPIPE, NULL, &pipeAction);
        sigaction(SIGSEGV, NULL, &faultAction);
        expect(@"signal handlers are restored after a run",
               pipeAction.sa_handler == SIG_IGN && faultAction.sa_handler == SIG_DFL);
        expect(@"terminal settings stay out of the process environment",
               !getenv("SSL_CERT_FILE") && !getenv("PYTHONHOME") && !getenv("CLICOLOR"));

        check(@"working directory", @"pwd\n", 0, here, 0);
        check(@"exit status", @"echo before\nexit 3\necho after\n", 3, @"before\n", 0);
        check(@"set -e", @"set -e\necho one\nfalse\necho two\n", 1, @"one\n", 0);
        check(@"unknown command", @"nosuchcommand_xyz\necho rc=$?\n", 0,
              [workDirectory stringByAppendingString:@"/script.sh: 1: nosuchcommand_xyz: not found\nrc=127\n"], 0);
        check(@"command stderr", @"ls /nonexistent_dir_xyz\necho rc=$?\n", 0,
              @"ls: /nonexistent_dir_xyz: No such file or directory\nrc=1\n", 0);
        check(@"variables and loop", @"total=0\nfor i in 1 2 3 4; do total=$((total + i)); done\necho total=$total\n", 0, @"total=10\n", 0);
        check(@"function and test", @"greet() { echo \"hi $1\"; }\nif [ -d . ]; then greet there; fi\n", 0, @"hi there\n", 0);
        check(@"file commands", @"mkdir -p sub/dir && echo one > sub/dir/a.txt && echo two >> sub/dir/a.txt\ncat sub/dir/a.txt\n"
              @"cp sub/dir/a.txt b.txt && mv b.txt c.txt && ls c.txt && rm -r sub c.txt\n", 0, @"one\ntwo\nc.txt\n", 0);
        check(@"pipeline", @"printf 'pear\\napple\\nfig\\n' | sort | head -2 | tr a-z A-Z\n", 0, @"APPLE\nFIG\n", 0);
        check(@"substitution", @"name=$(basename /a/b/c.txt)\necho \"got $name\"\n", 0, @"got c.txt\n", 0);
        check(@"heredoc sed awk", @"cat <<'END' > data.txt\nalpha 1\nbeta 2\ngamma 3\nEND\nsed -n '2p' data.txt\n"
              @"awk '{sum += $2} END {print sum}' data.txt\nrm data.txt\n", 0, @"beta 2\n6\n", 0);
        check(@"gzip", @"echo payload > t.txt && gzip t.txt && gunzip t.txt.gz && cat t.txt && rm t.txt\n", 0, @"payload\n", 0);
        check(@"find xargs", @"mkdir -p d && touch d/a.txt d/b.txt && find d -name '*.txt' | sort | xargs ls && rm -r d\n",
              0, @"d/a.txt\td/b.txt\n", 0);
        check(@"unicode names", @"mkdir -p '中文 目录' && echo '你好，世界' > '中文 目录/文件 一.txt' && cat '中文 目录/文件 一.txt' && rm -r '中文 目录'\n",
              0, @"你好，世界\n", 0);
        check(@"large output", @"i=0\nwhile [ $i -lt 5000 ]; do echo \"line $i padding padding padding padding padding\"; i=$((i+1)); done\n",
              0, nil, 0);
        check(@"background command", @"sleep 1 &\necho started\n", 0, @"started\n", 0);
        check(@"exported variable", @"export GA_PROBE=1\necho $GA_PROBE\n", 0, @"1\n", 0);
        expect(@"script variables stay out of the process environment", !getenv("GA_PROBE"));

        // Stopping: each script would otherwise run for 30 s or for ever.
        check(@"cancel sleep", @"echo begin\nsleep 30\necho end\n", ANY_STATUS, @"begin\n", 1);
        check(@"cancel loop", @"while true; do sleep 1; done\n", ANY_STATUS, @"", 1);
        check(@"cancel busy loop", @"while :; do :; done\n", ANY_STATUS, @"", 1);
        check(@"cancel in function", @"work() { while true; do sleep 1; done; }\nwork\nsleep 30\n", ANY_STATUS, @"", 1);
        check(@"cancel pipeline", @"sleep 30 | grep x | wc -l\n", ANY_STATUS, nil, 1);
        check(@"cancel background", @"sleep 30 &\nsleep 30\n", ANY_STATUS, @"", 1);
        check(@"cancel output loop", @"while true; do echo spam; done\n", ANY_STATUS, nil, 1);
        check(@"run after cancels", @"printf 'a\\nb\\n' | sort -r | head -1\n", 0, @"b\n", 0);

        // Known limits of the thread-based shell, pinned so that a change shows up here.
        check(@"limit: nested sh", @"echo 'echo inner' > inner.sh\ndash inner.sh\necho rc=$?\n. ./inner.sh\nrm inner.sh\n", 0,
              @"Too many instances of this command are already running. Please quit some of them or wait for them to end.\nrc=2\ninner\n", 0);
        check(@"limit: subshell cd", @"(cd / && pwd)\npwd\n", 0, @"/\n/\n", 0);
        check(@"limit: echo >&2", @"echo first\necho second >&2\necho third\n", 0, @"first\nthird\n", 0);
        printf("DONE failures=%d\n", failures);
    }
    return failures ? 1 : 0;
}
