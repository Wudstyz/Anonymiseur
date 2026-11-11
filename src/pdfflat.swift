import Foundation
import PDFKit
import AppKit

// Usage : pdfflat entrée.pdf sortie.pdf [dpi] [termes.json]
// Redessine chaque page en image (plus de texte, de polices ni de calques) et noircit au préalable les
// occurrences des termes donnés. Affiche sur la sortie standard {"terme": nombre d'occurrences noircies}.

let a = CommandLine.arguments
func die(_ msg: String, _ code: Int32) -> Never {
    FileHandle.standardError.write(Data((msg + "\n").utf8))
    exit(code)
}
guard a.count >= 3, let doc = PDFDocument(url: URL(fileURLWithPath: a[1])) else { die("lecture impossible", 2) }
if doc.isLocked { die("PDF verrouillé", 4) }
let dpi = a.count > 3 ? (Double(a[3]) ?? 150) : 150
var terms: [String] = []
if a.count > 4, let d = try? Data(contentsOf: URL(fileURLWithPath: a[4])),
   let t = try? JSONDecoder().decode([String].self, from: d) { terms = t }

// Rectangles à noircir, par page (coordonnées PDF, origine en bas à gauche).
// On cherche dans le texte sans espaces ni retours à la ligne (un terme peut être coupé en fin de ligne),
// puis on reconstitue un rectangle par ligne à partir de la boîte de chaque caractère.
var boxes: [Int: [CGRect]] = [:]
var counts: [String: Int] = [:]
let wanted = terms.map { t in (t, t.unicodeScalars.filter { !CharacterSet.whitespacesAndNewlines.contains($0) }.map(String.init).joined()) }
for i in 0..<doc.pageCount {
    guard let page = doc.page(at: i), let text = page.string else { continue }
    var compact = "", map: [Int] = []
    let ns = text as NSString
    for idx in 0..<ns.length {
        let ch = ns.substring(with: NSRange(location: idx, length: 1))
        if ch.unicodeScalars.allSatisfy({ CharacterSet.whitespacesAndNewlines.contains($0) }) { continue }
        compact += ch
        map.append(idx)
    }
    let cns = compact as NSString
    for (term, needle) in wanted where !needle.isEmpty {
        var from = 0
        while from < cns.length {
            let r = cns.range(of: needle, options: [.caseInsensitive], range: NSRange(location: from, length: cns.length - from))
            if r.location == NSNotFound { break }
            var lines: [CGRect] = []
            for k in r.location..<min(r.location + r.length, map.count) {
                let c = page.characterBounds(at: map[k])
                if c.width <= 0 || c.height <= 0 { continue }
                if let j = lines.lastIndex(where: { abs($0.midY - c.midY) < max($0.height, c.height) * 0.6 }) {
                    lines[j] = lines[j].union(c)
                } else {
                    lines.append(c)
                }
            }
            boxes[i, default: []].append(contentsOf: lines.map { $0.insetBy(dx: -1.5, dy: -1.5) })
            counts[term, default: 0] += 1
            from = r.location + max(r.length, 1)
        }
    }
}

var mediaBox = CGRect(x: 0, y: 0, width: 612, height: 792)
let aux = NSDictionary(dictionary: [kCGPDFContextCreator as String: "", kCGPDFContextTitle as String: ""])
guard let ctx = CGContext(URL(fileURLWithPath: a[2]) as CFURL, mediaBox: &mediaBox, aux as CFDictionary) else { die("écriture impossible", 3) }
let scale = dpi / 72.0

for i in 0..<doc.pageCount {
    guard let page = doc.page(at: i) else { continue }
    let box = page.bounds(for: .mediaBox)
    let rot = ((page.rotation % 360) + 360) % 360
    let swap = rot == 90 || rot == 270
    let pw = swap ? box.height : box.width, ph = swap ? box.width : box.height
    let px = max(1, Int(pw * scale)), py = max(1, Int(ph * scale))
    let img = page.thumbnail(of: NSSize(width: px, height: py), for: .mediaBox)
    guard var cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else { continue }
    if let rects = boxes[i], !rects.isEmpty, rot == 0,
       let b = CGContext(data: nil, width: px, height: py, bitsPerComponent: 8, bytesPerRow: 0,
                         space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue) {
        b.draw(cg, in: CGRect(x: 0, y: 0, width: px, height: py))
        b.setFillColor(CGColor(gray: 0, alpha: 1))
        for r in rects {
            b.fill(CGRect(x: (r.minX - box.minX) * scale, y: (r.minY - box.minY) * scale,
                          width: r.width * scale, height: r.height * scale))
        }
        if let m = b.makeImage() { cg = m }
    }
    var pb = CGRect(x: 0, y: 0, width: pw, height: ph)
    let pinfo = NSDictionary(dictionary: [kCGPDFContextMediaBox as String: Data(bytes: &pb, count: MemoryLayout<CGRect>.size)])
    ctx.beginPDFPage(pinfo as CFDictionary)
    ctx.draw(cg, in: pb)
    ctx.endPDFPage()
}
ctx.closePDF()
if let json = try? JSONEncoder().encode(counts), let s = String(data: json, encoding: .utf8) { print(s) }
