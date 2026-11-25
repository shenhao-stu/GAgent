import AVFoundation
import Speech
import UIKit

/// Both foreground audio clients use the main thread. Only the current owner may deactivate the mic.
enum MicrophoneSession {
    enum Client { case notes, dictation }
    private static var owner: Client?

    static func acquire(_ client: Client) throws {
        guard owner == nil else { throw VoiceFailure("microphone_busy") }
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.playAndRecord, mode: client == .dictation ? .measurement : .default,
                                options: client == .notes ? [.mixWithOthers] : [])
        try session.setActive(true)
        owner = client
    }

    static func release(_ client: Client) {
        guard owner == client else { return }
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        owner = nil
    }
}

private struct VoiceFailure: LocalizedError {
    let code: String
    init(_ code: String) { self.code = code }
    var errorDescription: String? { code }
}

/// One gesture owns one recognition task. The WK bridge and callbacks serialize state on the main queue.
final class VoiceInput: NSObject {
    static let shared = VoiceInput()
    private var id: UUID?
    private var engine: AVAudioEngine?
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var activeRecognizer: SFSpeechRecognizer?
    private var task: SFSpeechRecognitionTask?
    private var timeout: Timer?
    private var result: [String: Any] = ["done": true]

    private override init() {
        super.init()
        let center = NotificationCenter.default
        center.addObserver(self, selector: #selector(background), name: UIApplication.didEnterBackgroundNotification, object: nil)
        center.addObserver(self, selector: #selector(interrupted(_:)), name: AVAudioSession.interruptionNotification, object: nil)
    }

    private func recognizer(for language: String) -> SFSpeechRecognizer? {
        let locale = Locale(identifier: language.hasPrefix("en") ? "en-US" : "zh-CN")
        guard let recognizer = SFSpeechRecognizer(locale: locale), recognizer.supportsOnDeviceRecognition,
              recognizer.isAvailable else { return nil }
        return recognizer
    }

    func status(language: String) -> [String: Any] {
        ["modelReady": recognizer(for: language) != nil, "engine": "apple_on_device"]
    }

    func start(language: String) -> [String: Any] {
        do {
            guard engine == nil, task == nil else { throw VoiceFailure("microphone_busy") }
            guard UIApplication.shared.applicationState == .active else { throw VoiceFailure("foreground_required") }
            guard let recognizer = recognizer(for: language) else { throw VoiceFailure("local_speech_unavailable") }
            try checkPermissions()
            try MicrophoneSession.acquire(.dictation)

            let generation = UUID()
            id = generation
            result = ["done": false]
            let audio = AVAudioEngine()
            let req = SFSpeechAudioBufferRecognitionRequest()
            req.requiresOnDeviceRecognition = true
            req.shouldReportPartialResults = false
            req.taskHint = .dictation
            let input = audio.inputNode
            let format = input.outputFormat(forBus: 0)
            guard format.sampleRate > 0, format.channelCount > 0 else {
                MicrophoneSession.release(.dictation)
                throw VoiceFailure("microphone_unavailable")
            }
            input.installTap(onBus: 0, bufferSize: 1024, format: format) { buffer, _ in req.append(buffer) }
            engine = audio
            request = req
            do {
                audio.prepare()
                try audio.start()
            } catch {
                finish(error: "microphone_unavailable")
                throw VoiceFailure("microphone_unavailable")
            }
            activeRecognizer = recognizer
            task = recognizer.recognitionTask(with: req) { [weak self] transcript, error in
                DispatchQueue.main.async {
                    guard let self, self.id == generation, self.task != nil else { return }
                    if let transcript, transcript.isFinal {
                        self.finish(text: transcript.bestTranscription.formattedString)
                    } else if error != nil {
                        self.finish(error: "local_speech_failed")
                    }
                }
            }
            armTimeout(seconds: 60) { [weak self] in self?.stop(generation.uuidString) }
            return ["ok": true, "id": generation.uuidString]
        } catch {
            return ["ok": false, "error": (error as? VoiceFailure)?.code ?? "microphone_unavailable"]
        }
    }

    // The permission dialog can outlive the gesture: request access, never start recording from its callback.
    private func checkPermissions() throws {
        switch AVAudioApplication.shared.recordPermission {
        case .granted: break
        case .undetermined:
            AVAudioApplication.requestRecordPermission { _ in }
            throw VoiceFailure("permission_requested")
        default: throw VoiceFailure("microphone_denied")
        }
        switch SFSpeechRecognizer.authorizationStatus() {
        case .authorized: break
        case .notDetermined:
            SFSpeechRecognizer.requestAuthorization { _ in }
            throw VoiceFailure("permission_requested")
        default: throw VoiceFailure("speech_denied")
        }
    }

    func poll(_ token: String) -> [String: Any] {
        guard token == id?.uuidString else { return ["done": true, "error": "recording_ended"] }
        return result
    }

    func stop(_ token: String) {
        guard token == id?.uuidString, engine != nil else { return }
        closeInput()
        armTimeout(seconds: 8) { [weak self] in self?.finish(error: "local_speech_timeout") }
    }

    func cancel(_ token: String) {
        guard token == id?.uuidString else { return }
        finish(error: "recording_ended")
    }

    private func closeInput() {
        guard let audio = engine else { return }
        audio.stop()
        audio.inputNode.removeTap(onBus: 0)
        request?.endAudio()
        engine = nil
        request = nil
        MicrophoneSession.release(.dictation)
    }

    private func finish(text: String = "", error: String? = nil) {
        timeout?.invalidate()
        timeout = nil
        closeInput()
        let prior = task
        task = nil
        prior?.cancel()
        activeRecognizer = nil
        result = ["done": true, "text": text]
        if let error { result["error"] = error }
    }

    private func armTimeout(seconds: TimeInterval, _ action: @escaping () -> Void) {
        timeout?.invalidate()
        timeout = Timer.scheduledTimer(withTimeInterval: seconds, repeats: false) { _ in action() }
    }

    @objc private func background() { if task != nil { finish(error: "recording_ended") } }
    @objc private func interrupted(_ note: Notification) {
        if let reason = note.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt,
           reason == AVAudioSession.InterruptionType.began.rawValue {
            DispatchQueue.main.async { [weak self] in self?.background() }
        }
    }
}
