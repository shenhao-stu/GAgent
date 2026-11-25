# Physical iPhone OCR regression fixtures

Two unmodified ReplayKit JPEGs from the GAgent UIKit acceptance page, 740×1600. They contain generated test UI, no user data. On iOS26.6.2 the legacy VNRecognizeTextRequest omitted three Chinese button labels across these frames, despite Mac recognizing all labels. ScreenRecognitionTests exercises the production service and checks text plus top-left coordinates. Run on a physical iPhone as well as simulator; OS Vision results differ.

SHA256:
- chinese-buttons-0.jpg: 00f5b8fe79e156a474528a201c7d04a530d580c67db68eb47dba446f8e218bae
- chinese-buttons-1.jpg: 4a0b16e91ba420da68e48902e1b736736c601a9336e45254a187e8f6b0a84b9b

XcodeGen's BoardKitTests sources include these JPEGs as test bundle resources. Full investigation and device build2611150220 evidence: IOSAgent/work/ocr-fix-20261115/REPORT.md.
