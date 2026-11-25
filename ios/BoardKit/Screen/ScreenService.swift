import CoreGraphics
import Foundation
import Vision

/// The `screen` tool: turns the selected source's frames into observations the model can act on
/// (an image, its frame id and numbered elements). It reads only; it holds no input device.
@MainActor final class ScreenService {
    private(set) var source: CaptureSource
    private var observation = ScreenObservation()
    private var lastReading: (id: String, value: ScreenElements.Reading)?
    /// Where a visible pointer is, so frame comparisons can mask it. Injected; nil when there is no pointer.
    var pointerLocation: () -> CGPoint? = { nil }
    /// Text and controls of one frame. Replaceable in tests.
    var read: @Sendable (Data) async throws -> ScreenElements.Reading = { try await ScreenService.readElements($0) }

    init(source: CaptureSource) { self.source = source }

    var generation: Int { source.generation }
    var sharing: Bool { source.sharing }
    var preview: Data? { source.preview }

    func select(_ next: CaptureSource) {
        let previous = source
        source = next
        if previous !== next { previous.setSelected(false) }
        next.setSelected(true)
    }

    /// Drop every published observation: after a stop, a handoff or a new sharing session old ids are void.
    func forget() {
        observation = ScreenObservation()
        lastReading = nil
    }

    /// A current frame for an internal check. No observation id is published for it.
    func currentFrame() async throws -> CapturedFrame {
        var frame = try await source.frame()
        frame.pointer = pointerLocation()
        return frame
    }

    /// Whether a touch at `target`, aimed on observation `expected`, is still valid on `current`. Returns true when
    /// the page changed elsewhere.
    func require(_ expected: String?, current: CapturedFrame, target: CGPoint?) throws -> Bool {
        try observation.require(expected, current: current.jpeg, generation: current.generation,
                                target: target, pointer: pointerLocation())
    }

    func targetMasked(_ target: CGPoint, on id: String) -> Bool {
        observation.targetMasked(target, on: id, pointer: pointerLocation())
    }

    /// Observation `id` belongs to the sharing session that is running now.
    func requireKnown(_ id: String) throws { try observation.requireKnown(id, generation: generation) }

    /// One observation. `textBoxes` adds the recognized text with its boxes (and leaves the image out when text was read).
    func observe(marks: Bool = false, ocr: Bool = true, region: [String: Any]? = nil,
                 textBoxes: Bool = false, image: Bool = true) async throws -> [String: Any] {
        let started = ProcessInfo.processInfo.systemUptime
        let original = try await currentFrame()
        let captured = ProcessInfo.processInfo.systemUptime
        let reading: ScreenElements.Reading
        if !ocr && !textBoxes && !marks { reading = .skipped }
        else if let cached = lastReading, observation.isExact(original.jpeg, generation: original.generation, id: cached.id) {
            reading = cached.value
        } else {
            let read = self.read
            reading = try await Task.detached { try await read(original.jpeg) }.value
        }
        let recognized = ProcessInfo.processInfo.systemUptime

        // Recognition can outlive a disconnect, a user stop or the frame's freshness proof.
        try source.requireReadable(generation: original.generation)
        var latest = try await source.presentable(original)
        if latest.pointer == nil { latest.pointer = pointerLocation() }
        guard latest.generation == original.generation else { throw ScreenObservation.Failure.frameChanged }

        // A moving screen can advance during OCR. Never attach old labels to a different picture.
        // If the original still has a live proof and the page is visually unchanged, return *its own* pixels and labels.
        let current = latest.jpeg == original.jpeg
        let stillVisible = !current && source.proves(original)
            && !Vision.changed(original.jpeg, latest.jpeg, ignore: [original.pointer, latest.pointer].compactMap { $0 })
        let frame = stillVisible ? original : latest
        let annotation: ScreenElements.Reading = current || stillVisible ? reading : .frameChanged
        let validated = ProcessInfo.processInfo.systemUptime
        let same = observation.samePage(frame.jpeg, generation: frame.generation, pointer: frame.pointer)
        let id = observation.capture(frame.jpeg, generation: frame.generation, pointer: frame.pointer)
        let found = annotation.elements
        if annotation.cacheable { lastReading = (id, annotation) }
        else if lastReading?.id != id { lastReading = nil }
        var result: [String: Any] = [
            "ok": true, "frame_id": id, "captured_at": frame.capturedAt, "same_as_previous": same,
            "capture_source": source.name, "capture_generation": frame.generation,
            "width": Int(frame.size.width), "height": Int(frame.size.height), "coordinate_system": "normalized_top_left",
            "elements": found.map(\.summary), "element_sources": annotation.sources,
            "elements_ms": Int((recognized - captured) * 1000)]
        result["sample_sequence"] = frame.sequence
        result["sample_uptime"] = frame.sampleUptime
        if textBoxes {
            result["boxes"] = annotation.texts.map {
                ["text": $0.string, "confidence": $0.confidence, "x": $0.box.minX, "y": $0.box.minY,
                 "width": $0.box.width, "height": $0.box.height] as [String: Any]
            }
        }
        if image && (!textBoxes || annotation.texts.isEmpty) {
            let marked = marks && !found.isEmpty ? ScreenElements.marked(frame.jpeg, found) : nil
            result["image_base64"] = (marked ?? frame.jpeg).base64EncodedString()
            result["mime_type"] = "image/jpeg"
            if marks { result["marked"] = marked != nil }
        }
        if image, let region {
            result["detail_image_base64"] = try ScreenElements.detail(frame.jpeg, region: region).base64EncodedString()
            result["detail_region"] = region
            result["detail_note"] = "Second image is an enlargement for reading only. All action coordinates refer to the first, full-screen image."
        }
        result["timing_ms"] = ["capture": Int((captured - started) * 1000),
            "recognition": Int((recognized - captured) * 1000), "validation": Int((validated - recognized) * 1000),
            "presentation": Int((ProcessInfo.processInfo.systemUptime - validated) * 1000)]
        return result
    }

    nonisolated static func readElements(_ frame: Data) async throws -> ScreenElements.Reading {
        try await ScreenElements.read(text: { try await recognize(frame) }, controls: nil)
    }

    /// Text lines with normalized top-left boxes.
    nonisolated private static func recognize(_ data: Data) async throws -> [ScreenElements.Text] {
        if #available(iOS 18, *) {
            var request = RecognizeTextRequest()
            request.recognitionLevel = .accurate
            request.automaticallyDetectsLanguage = true
            request.recognitionLanguages = [Locale.Language(identifier: "zh-Hans"), Locale.Language(identifier: "en-US")]
            request.usesLanguageCorrection = true
            return try await request.perform(on: data).compactMap { result in
                guard let candidate = result.topCandidates(1).first else { return nil }
                return ScreenElements.Text(box: result.boundingBox.verticallyFlipped().cgRect,
                                           string: candidate.string, confidence: candidate.confidence)
            }
        }
        let request = VNRecognizeTextRequest()
        request.recognitionLevel = .accurate
        request.recognitionLanguages = ["zh-Hans", "en-US"]
        request.usesLanguageCorrection = true
        try VNImageRequestHandler(data: data, options: [:]).perform([request])
        return (request.results ?? []).compactMap { result in
            guard let candidate = result.topCandidates(1).first else { return nil }
            let b = result.boundingBox
            return ScreenElements.Text(box: CGRect(x: b.minX, y: 1 - b.maxY, width: b.width, height: b.height),
                                       string: candidate.string, confidence: candidate.confidence)
        }
    }
}
