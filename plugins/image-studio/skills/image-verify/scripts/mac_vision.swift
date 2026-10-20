// Apple Vision helpers for image-studio (macOS 14+). No model download: the models ship with macOS.
// Built and run by mac_vision.py; see that file for usage. Prints one JSON object on stdout.
//   cutout IN OUTDIR [X Y]   foreground cutout.png, mask.png, and mask-N.png per instance; X Y (pixels) keeps one instance
//   ocr IN                   text lines with confidence and boxes [x0, y0, x1, y1] in image pixels
//   hands IN                 one box per detected hand with the number of the 21 joints seen
// Exit codes: 0 written, 1 nothing found, 2 bad input.
import CoreImage
import Foundation
import ImageIO
import UniformTypeIdentifiers
import Vision

func fail(_ message: String) -> Never { FileHandle.standardError.write(("error: " + message + "\n").data(using: .utf8)!); exit(2) }

func emit(_ object: [String: Any], code: Int32 = 0) -> Never {
    let data = try! JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
    print(String(data: data, encoding: .utf8)!)
    exit(code)
}

func load(_ path: String) -> CGImage {
    guard let source = CGImageSourceCreateWithURL(URL(fileURLWithPath: path) as CFURL, nil),
          let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else { fail("cannot read image \(path)") }
    return image
}

let context = CIContext()
func writePNG(_ image: CIImage, _ path: String, _ extent: CGRect) {
    guard let cg = context.createCGImage(image, from: extent, format: .RGBA8, colorSpace: CGColorSpace(name: CGColorSpace.sRGB)!),
          let dest = CGImageDestinationCreateWithURL(URL(fileURLWithPath: path) as CFURL, UTType.png.identifier as CFString, 1, nil)
    else { fail("cannot write \(path)") }
    CGImageDestinationAddImage(dest, cg, nil)
    if !CGImageDestinationFinalize(dest) { fail("cannot write \(path)") }
}

let args = CommandLine.arguments
guard args.count >= 3 else { fail("usage: cutout IN OUTDIR [X Y] | ocr IN | hands IN") }
let image = load(args[2])
let W = Double(image.width), H = Double(image.height)
let handler = VNImageRequestHandler(cgImage: image, options: [:])
let start = Date()

switch args[1] {
case "cutout":
    guard args.count == 4 || args.count == 6 else { fail("usage: cutout IN OUTDIR [X Y]") }
    let outDir = args[3]
    do { try FileManager.default.createDirectory(atPath: outDir, withIntermediateDirectories: true) } catch { fail("cannot create \(outDir)") }
    let request = VNGenerateForegroundInstanceMaskRequest()
    do { try handler.perform([request]) } catch { fail("Vision failed: \(error.localizedDescription)") }
    guard let result = request.results?.first, !result.allInstances.isEmpty else {
        emit(["instances": 0, "seconds": Date().timeIntervalSince(start)], code: 1)
    }
    var chosen = result.allInstances
    var picked: Int? = nil
    if args.count == 6 {
        guard let x = Double(args[4]), let y = Double(args[5]), x >= 0, y >= 0, x < W, y < H else { fail("X Y must be a pixel inside the image") }
        let labels = result.instanceMask
        CVPixelBufferLockBaseAddress(labels, .readOnly)
        let mw = CVPixelBufferGetWidth(labels), mh = CVPixelBufferGetHeight(labels), row = CVPixelBufferGetBytesPerRow(labels)
        let px = min(mw - 1, Int(x / W * Double(mw))), py = min(mh - 1, Int(y / H * Double(mh)))
        let label = Int(CVPixelBufferGetBaseAddress(labels)!.assumingMemoryBound(to: UInt8.self)[py * row + px])
        CVPixelBufferUnlockBaseAddress(labels, .readOnly)
        if label == 0 { emit(["instances": result.allInstances.count, "picked": 0, "seconds": Date().timeIntervalSince(start)], code: 1) }
        chosen = IndexSet(integer: label)
        picked = label
    }
    let source = CIImage(cgImage: image)
    do {
        let mask = CIImage(cvPixelBuffer: try result.generateScaledMaskForImage(forInstances: chosen, from: handler))
        let cut = source.applyingFilter("CIBlendWithMask", parameters: [kCIInputBackgroundImageKey: CIImage.empty(), kCIInputMaskImageKey: mask])
        writePNG(cut, outDir + "/cutout.png", source.extent)
        writePNG(mask, outDir + "/mask.png", source.extent)
        for i in result.allInstances {
            let one = CIImage(cvPixelBuffer: try result.generateScaledMaskForImage(forInstances: IndexSet(integer: i), from: handler))
            writePNG(one, outDir + "/mask-\(i).png", source.extent)
        }
    } catch { fail("mask failed: \(error.localizedDescription)") }
    var out: [String: Any] = ["instances": result.allInstances.count, "ids": Array(result.allInstances),
                              "files": ["cutout.png", "mask.png"], "seconds": Date().timeIntervalSince(start)]
    if let picked = picked { out["picked"] = picked }
    emit(out)

case "ocr":
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = false
    do { try handler.perform([request]) } catch { fail("Vision failed: \(error.localizedDescription)") }
    var lines: [[String: Any]] = []
    for observation in request.results ?? [] {
        guard let best = observation.topCandidates(1).first else { continue }
        let r = observation.boundingBox  // normalized, bottom-left origin
        lines.append(["text": best.string, "confidence": Double(best.confidence),
                      "box": [Int((r.minX * W).rounded()), Int(((1 - r.maxY) * H).rounded()), Int((r.maxX * W).rounded()), Int(((1 - r.minY) * H).rounded())]])
    }
    emit(["lines": lines, "seconds": Date().timeIntervalSince(start)], code: lines.isEmpty ? 1 : 0)

case "hands":
    let request = VNDetectHumanHandPoseRequest()
    request.maximumHandCount = 12
    do { try handler.perform([request]) } catch { fail("Vision failed: \(error.localizedDescription)") }
    var hands: [[String: Any]] = []
    for observation in request.results ?? [] {
        guard let points = try? observation.recognizedPoints(.all) else { continue }
        let seen = points.values.filter { $0.confidence > 0.3 }
        if seen.isEmpty { continue }
        let xs = seen.map { $0.location.x * W }, ys = seen.map { (1 - $0.location.y) * H }
        let x0 = xs.min()!, x1 = xs.max()!, y0 = ys.min()!, y1 = ys.max()!
        let pad = max(16.0, 0.3 * max(x1 - x0, y1 - y0))  // joints sit inside the hand: pad to the skin edge
        let side = observation.chirality == .left ? "left" : (observation.chirality == .right ? "right" : "unknown")
        hands.append(["joints": seen.count, "side": side, "confidence": Double(observation.confidence),
                      "box": [Int(max(0, x0 - pad)), Int(max(0, y0 - pad)), Int(min(W, x1 + pad)), Int(min(H, y1 + pad))]])
    }
    emit(["hands": hands, "seconds": Date().timeIntervalSince(start)], code: hands.isEmpty ? 1 : 0)

default:
    fail("unknown command \(args[1]); use cutout, ocr, or hands")
}
