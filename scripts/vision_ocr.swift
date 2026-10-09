import Foundation
import Vision
import ImageIO
let url = URL(fileURLWithPath: CommandLine.arguments[1])
let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.recognitionLanguages = ["ko-KR", "en-US"]
request.usesLanguageCorrection = true
do {
    try VNImageRequestHandler(url: url).perform([request])
} catch {
    fputs("OCR engine could not process this image.\n", stderr)
    exit(1)
}
let lines = (request.results ?? []).compactMap { $0.topCandidates(1).first?.string }
print(lines.joined(separator: "\n"))
