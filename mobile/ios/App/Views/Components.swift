import SwiftUI
import Foundation

enum Brand {
    static let accent = Color(red: 0.75, green: 0.37, blue: 0.49)
    static let background = Color(uiColor: .systemGroupedBackground)
}

struct ErrorNotice: View {
    let text: String
    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: "exclamationmark.circle")
            Text(text).font(.footnote).fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
        }
        .foregroundStyle(.orange).padding(12)
        .background(.orange.opacity(0.08), in: RoundedRectangle(cornerRadius: 12))
        .accessibilityIdentifier("errorNotice")
    }
}

/// 只绘制服务端验证码用到的图形，不执行 SVG 脚本、不访问外部资源。
struct CaptchaImage: View {
    private let elements: [SVGElement]
    init(svg: String) { elements = SVGReader.read(svg) }
    var body: some View {
        Canvas { context, size in
            context.scaleBy(x: size.width / 128, y: size.height / 48)
            for item in elements {
                var drawing = context
                drawing.opacity = Double(item.attributes["opacity"] ?? "1") ?? 1
                let a = item.attributes
                func n(_ key: String) -> Double { Double(a[key] ?? "0") ?? 0 }
                func color(_ key: String) -> Color {
                    let hex = (a[key] ?? "#000000").replacingOccurrences(of: "#", with: "")
                    let value = UInt(hex, radix: 16) ?? 0
                    return Color(red: Double((value >> 16) & 255) / 255, green: Double((value >> 8) & 255) / 255, blue: Double(value & 255) / 255)
                }
                switch item.name {
                case "rect":
                    let w = a["width"] == "100%" ? 128 : n("width")
                    let h = a["height"] == "100%" ? 48 : n("height")
                    let path = Path(roundedRect: CGRect(x: n("x"), y: n("y"), width: w, height: h), cornerRadius: n("rx"))
                    if a["fill"] != "none" { drawing.fill(path, with: .color(color("fill"))) }
                    if a["stroke"] != nil { drawing.stroke(path, with: .color(color("stroke")), lineWidth: 1) }
                case "circle":
                    drawing.fill(Path(ellipseIn: CGRect(x: n("cx") - n("r"), y: n("cy") - n("r"), width: n("r") * 2, height: n("r") * 2)), with: .color(color("fill")))
                case "line":
                    var path = Path(); path.move(to: CGPoint(x: n("x1"), y: n("y1"))); path.addLine(to: CGPoint(x: n("x2"), y: n("y2")))
                    drawing.stroke(path, with: .color(color("stroke")), lineWidth: 1)
                case "text":
                    let rotation = (a["transform"] ?? "").replacingOccurrences(of: "rotate(", with: "").split(separator: " ").first.flatMap { Double($0) } ?? 0
                    drawing.translateBy(x: n("x"), y: n("y")); drawing.rotate(by: .degrees(rotation))
                    drawing.draw(Text(item.text).font(.system(size: n("font-size"), weight: .heavy, design: .monospaced)).foregroundColor(color("fill")), at: CGPoint(x: 0, y: 4), anchor: .bottomLeading)
                default: break
                }
            }
        }.frame(width: 128, height: 48).accessibilityHidden(true)
    }
}

private struct SVGElement { let name: String; let attributes: [String: String]; var text = "" }
private final class SVGReader: NSObject, XMLParserDelegate {
    private var elements: [SVGElement] = []
    static func read(_ value: String) -> [SVGElement] {
        guard value.utf8.count < 100_000, let data = value.data(using: .utf8) else { return [] }
        let reader = SVGReader(); let parser = XMLParser(data: data)
        parser.shouldResolveExternalEntities = false; parser.delegate = reader
        return parser.parse() ? reader.elements : []
    }
    func parser(_ parser: XMLParser, didStartElement elementName: String, namespaceURI: String?, qualifiedName qName: String?, attributes attributeDict: [String: String]) {
        if ["rect", "circle", "line", "text"].contains(elementName) { elements.append(SVGElement(name: elementName, attributes: attributeDict)) }
    }
    func parser(_ parser: XMLParser, foundCharacters string: String) {
        if elements.last?.name == "text" { elements[elements.count - 1].text += string }
    }
}
