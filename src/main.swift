import Cocoa
import WebKit

/// WKWebView qui intercepte les fichiers déposés depuis le Finder pour en récupérer le chemin sur le disque
/// (le navigateur n'en donne que le contenu). Les autres glisser-déposer restent gérés par la page.
final class DropWebView: WKWebView {
    var onFiles: (([URL]) -> Void)?

    override func performDragOperation(_ sender: NSDraggingInfo) -> Bool {
        let opts: [NSPasteboard.ReadingOptionKey: Any] = [.urlReadingFileURLsOnly: true]
        if let urls = sender.draggingPasteboard.readObjects(forClasses: [NSURL.self], options: opts) as? [URL], !urls.isEmpty {
            onFiles?(urls)
            return true
        }
        return super.performDragOperation(sender)
    }
}

/// Fenêtre native qui affiche l'interface et pilote le moteur Python local (127.0.0.1, port libre).
final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate, WKDownloadDelegate, WKScriptMessageHandler {
    var window: NSWindow!
    var web: DropWebView!
    var server: Process?
    var port: UInt16 = 0
    let token = UUID().uuidString          // protège les routes du moteur qui lisent le disque
    var downloadTarget: URL?
    var pageReady = false
    var pending: [String] = []
    var neutralDates = false
    let neutralDate = Date(timeIntervalSince1970: 946684800)   // 1er janvier 2000

    func applicationDidFinishLaunching(_ note: Notification) {
        buildMenu()
        let cfg = WKWebViewConfiguration()
        cfg.userContentController.add(self, name: "native")
        cfg.userContentController.addUserScript(WKUserScript(
            source: "window.NATIVE = true; window.TOKEN = '\(token)';",
            injectionTime: .atDocumentStart, forMainFrameOnly: true))
        web = DropWebView(frame: .zero, configuration: cfg)
        web.navigationDelegate = self
        web.uiDelegate = self
        web.onFiles = { [weak self] urls in
            self?.web.evaluateJavaScript("document.getElementById('drop').classList.remove('over')")
            self?.openPaths(urls.map { $0.path })
        }
        web.loadHTMLString("<body style='font:15px -apple-system;color:#888;display:flex;height:90vh;align-items:center;justify-content:center'>Démarrage…</body>", baseURL: nil)

        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 780, height: 740),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable],
                          backing: .buffered, defer: false)
        window.title = "Anonymiseur"
        window.contentView = web
        window.minSize = NSSize(width: 480, height: 480)
        window.center()
        window.setFrameAutosaveName("MainWindow")
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)

        guard startServer() else { return }
        DispatchQueue.global().async {
            for _ in 0..<80 {
                if self.ping() {
                    DispatchQueue.main.async { self.web.load(URLRequest(url: URL(string: "http://127.0.0.1:\(self.port)/")!)) }
                    return
                }
                usleep(125_000)
            }
            DispatchQueue.main.async { self.fail("Le moteur d'anonymisation ne répond pas.") }
        }
    }

    // MARK: fichiers ouverts depuis le Finder / déposés sur l'icône du Dock

    func application(_ sender: NSApplication, openFiles filenames: [String]) {
        openPaths(filenames)
        sender.reply(toOpenOrPrint: .success)
    }

    func openPaths(_ paths: [String]) {
        guard pageReady else { pending += paths; return }
        guard let data = try? JSONSerialization.data(withJSONObject: paths),
              let json = String(data: data, encoding: .utf8) else { return }
        web.evaluateJavaScript("window.openPaths && window.openPaths(\(json))")
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        guard webView.url?.host == "127.0.0.1" else { return }
        pageReady = true
        if !pending.isEmpty { let p = pending; pending = []; openPaths(p) }
    }

    // MARK: messages venant de la page

    func userContentController(_ ucc: WKUserContentController, didReceive message: WKScriptMessage) {
        guard let body = message.body as? [String: Any], let type = body["type"] as? String else { return }
        switch type {
        case "options":
            neutralDates = body["neutral"] as? Bool ?? false
        case "saveText":
            let p = NSSavePanel()
            p.nameFieldStringValue = body["name"] as? String ?? "rapport.txt"
            p.directoryURL = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask).first
            p.beginSheetModal(for: window) { r in
                guard r == .OK, let u = p.url, let t = body["text"] as? String else { return }
                try? t.write(to: u, atomically: true, encoding: .utf8)
                NSWorkspace.shared.activateFileViewerSelecting([u])
            }
        case "trash":
            trash(body["items"] as? [[String: Any]] ?? [])
        case "pick":
            let p = NSOpenPanel()
            p.allowsMultipleSelection = true
            p.canChooseDirectories = true
            p.message = "Choisissez des fichiers ou des dossiers à anonymiser"
            p.prompt = "Choisir"
            p.beginSheetModal(for: window) { r in
                if r == .OK { self.openPaths(p.urls.map { $0.path }) }
            }
        case "reveal":
            if let path = body["path"] as? String {
                NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: path)])
            }
        case "saveAll":
            saveAll(body["items"] as? [[String: Any]] ?? [])
        default: break
        }
    }

    func applyNeutral(_ url: URL) {
        guard neutralDates else { return }
        try? FileManager.default.setAttributes([.modificationDate: neutralDate, .creationDate: neutralDate], ofItemAtPath: url.path)
    }

    /// Met les originaux à la corbeille, après confirmation, et seulement si la copie anonymisée existe bien.
    func trash(_ items: [[String: Any]]) {
        let fm = FileManager.default
        let pairs: [(URL, URL)] = items.compactMap { it in
            guard let s = it["src"] as? String, let c = it["copy"] as? String, s != c,
                  fm.fileExists(atPath: s), fm.fileExists(atPath: c) else { return nil }
            return (URL(fileURLWithPath: s), URL(fileURLWithPath: c))
        }
        guard !pairs.isEmpty else { return }
        let a = NSAlert()
        a.messageText = pairs.count == 1 ? "Mettre l'original à la corbeille ?" : "Mettre \(pairs.count) originaux à la corbeille ?"
        let names = pairs.prefix(8).map { "• " + $0.0.lastPathComponent }.joined(separator: "\n")
        a.informativeText = "Les copies anonymisées sont enregistrées. Les originaux contiennent encore leurs métadonnées :\n\(names)"
            + (pairs.count > 8 ? "\n…" : "") + "\n\nIls restent récupérables dans la corbeille."
        a.addButton(withTitle: "Mettre à la corbeille")
        a.addButton(withTitle: "Garder")
        a.beginSheetModal(for: window) { resp in
            guard resp == .alertFirstButtonReturn else { return }
            var n = 0
            for (src, _) in pairs where (try? fm.trashItem(at: src, resultingItemURL: nil)) != nil { n += 1 }
            self.web.evaluateJavaScript("window.nativeTrashed && window.nativeTrashed(\(n))")
        }
    }

    func saveAll(_ items: [[String: Any]]) {
        let p = NSOpenPanel()
        p.canChooseFiles = false
        p.canChooseDirectories = true
        p.canCreateDirectories = true
        p.prompt = "Enregistrer ici"
        p.message = "Choisissez le dossier où enregistrer les fichiers nettoyés"
        p.beginSheetModal(for: window) { r in
            guard r == .OK, let dir = p.url else { return }
            DispatchQueue.global().async {
                var saved: [URL] = []
                for it in items {
                    guard let id = it["id"] as? String, let name = it["name"] as? String else { continue }
                    var c = URLComponents(string: "http://127.0.0.1:\(self.port)/result")!
                    c.queryItems = [URLQueryItem(name: "id", value: id), URLQueryItem(name: "token", value: self.token)]
                    guard let data = try? Data(contentsOf: c.url!) else { continue }
                    let dest = self.uniqueURL(dir, name)
                    if (try? data.write(to: dest, options: .withoutOverwriting)) != nil {
                        DispatchQueue.main.sync { self.applyNeutral(dest) }
                        saved.append(dest)
                    }
                }
                DispatchQueue.main.async {
                    if !saved.isEmpty { NSWorkspace.shared.activateFileViewerSelecting(saved) }
                    self.web.evaluateJavaScript("window.nativeSaved && window.nativeSaved(\(saved.count))")
                }
            }
        }
    }

    func uniqueURL(_ dir: URL, _ name: String) -> URL {
        let base = (name as NSString).deletingPathExtension, ext = (name as NSString).pathExtension
        var url = dir.appendingPathComponent(name), i = 2
        while FileManager.default.fileExists(atPath: url.path) {
            url = dir.appendingPathComponent(ext.isEmpty ? "\(base) \(i)" : "\(base) \(i).\(ext)")
            i += 1
        }
        return url
    }

    // MARK: moteur Python

    func startServer() -> Bool {
        // Tout est embarqué dans l'app : Python, FFmpeg, ExifTool. Rien n'est cherché ailleurs sur le Mac
        // (sauf les outils du système : perl, sips).
        let res = Bundle.main.resourcePath!
        let py = res + "/python/bin/python3"
        guard FileManager.default.isExecutableFile(atPath: py) else {
            fail("Le composant Python intégré à l'app est introuvable : réinstallez Anonymiseur.")
            return false
        }
        port = freePort()
        let p = Process()
        p.executableURL = URL(fileURLWithPath: py)
        p.arguments = [res + "/server.py", "--no-browser"]
        p.environment = [
            "PORT": String(port),
            "TOKEN": token,
            "PDFFLAT": Bundle.main.bundlePath + "/Contents/MacOS/pdfflat",
            "PATH": res + "/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": NSHomeDirectory(),
            "LANG": "fr_FR.UTF-8",
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        ]
        p.standardOutput = FileHandle.nullDevice
        p.standardError = FileHandle.nullDevice
        do { try p.run() } catch { fail("Impossible de démarrer le moteur : \(error.localizedDescription)"); return false }
        server = p
        return true
    }

    /// Port stable (pour que la page retrouve ses réglages d'un lancement à l'autre) ; au hasard s'il est pris.
    func freePort() -> UInt16 { tryBind(48765) ?? tryBind(0) ?? 48766 }

    func tryBind(_ wanted: UInt16) -> UInt16? {
        let fd = socket(AF_INET, SOCK_STREAM, 0)
        defer { close(fd) }
        var addr = sockaddr_in()
        addr.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        addr.sin_family = sa_family_t(AF_INET)
        addr.sin_addr.s_addr = inet_addr("127.0.0.1")
        addr.sin_port = wanted.bigEndian
        let rc = withUnsafePointer(to: &addr) { $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { Darwin.bind(fd, $0, socklen_t(MemoryLayout<sockaddr_in>.size)) } }
        if rc != 0 { return nil }
        var len = socklen_t(MemoryLayout<sockaddr_in>.size)
        _ = withUnsafeMutablePointer(to: &addr) { $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { getsockname(fd, $0, &len) } }
        return UInt16(bigEndian: addr.sin_port)
    }

    func ping() -> Bool {
        var ok = false
        let sem = DispatchSemaphore(value: 0)
        var req = URLRequest(url: URL(string: "http://127.0.0.1:\(port)/ping")!)
        req.timeoutInterval = 1
        URLSession.shared.dataTask(with: req) { _, r, _ in
            ok = (r as? HTTPURLResponse)?.statusCode == 204
            sem.signal()
        }.resume()
        sem.wait()
        return ok
    }

    func fail(_ message: String) {
        let a = NSAlert()
        a.messageText = "Anonymiseur"
        a.informativeText = message
        a.runModal()
        NSApp.terminate(nil)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ app: NSApplication) -> Bool { true }
    func applicationWillTerminate(_ note: Notification) { server?.terminate() }

    // MARK: sélection de fichiers (<input type="file">, hors flux natif)

    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
        let p = NSOpenPanel()
        p.allowsMultipleSelection = parameters.allowsMultipleSelection
        p.canChooseDirectories = false
        p.prompt = "Choisir"
        p.beginSheetModal(for: window) { completionHandler($0 == .OK ? p.urls : nil) }
    }

    // MARK: téléchargements → boîte « Enregistrer sous »

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if action.shouldPerformDownload { decisionHandler(.download); return }
        // Garde l'interface locale : tout lien externe s'ouvre dans le navigateur.
        if let url = action.request.url, let host = url.host, host != "127.0.0.1", url.scheme?.hasPrefix("http") == true {
            NSWorkspace.shared.open(url)
            decisionHandler(.cancel)
            return
        }
        decisionHandler(.allow)
    }

    func webView(_ webView: WKWebView, decidePolicyFor response: WKNavigationResponse,
                 decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        let disposition = (response.response as? HTTPURLResponse)?.value(forHTTPHeaderField: "Content-Disposition") ?? ""
        decisionHandler(response.canShowMIMEType && !disposition.hasPrefix("attachment") ? .allow : .download)
    }

    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) { download.delegate = self }
    func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) { download.delegate = self }

    func download(_ download: WKDownload, decideDestinationUsing response: URLResponse,
                  suggestedFilename: String, completionHandler: @escaping (URL?) -> Void) {
        let p = NSSavePanel()
        p.nameFieldStringValue = suggestedFilename
        p.directoryURL = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask).first
        p.beginSheetModal(for: window) { r in
            self.downloadTarget = r == .OK ? p.url : nil
            if let u = p.url, r == .OK { try? FileManager.default.removeItem(at: u) }
            completionHandler(self.downloadTarget)
        }
    }

    func downloadDidFinish(_ download: WKDownload) {
        if let u = downloadTarget { applyNeutral(u); NSWorkspace.shared.activateFileViewerSelecting([u]) }
    }

    func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) {
        let a = NSAlert()
        a.messageText = "Échec de l'enregistrement"
        a.informativeText = error.localizedDescription
        a.beginSheetModal(for: window)
    }

    // MARK: menus

    func buildMenu() {
        let main = NSMenu()
        func add(_ title: String, _ items: [(String, Selector, String)]) {
            let item = NSMenuItem(); main.addItem(item)
            let menu = NSMenu(title: title); item.submenu = menu
            for (t, sel, key) in items { menu.addItem(NSMenuItem(title: t, action: sel, keyEquivalent: key)) }
        }
        add("Anonymiseur", [("Quitter Anonymiseur", #selector(NSApplication.terminate(_:)), "q")])
        add("Édition", [("Couper", #selector(NSText.cut(_:)), "x"), ("Copier", #selector(NSText.copy(_:)), "c"),
                        ("Coller", #selector(NSText.paste(_:)), "v"), ("Tout sélectionner", #selector(NSText.selectAll(_:)), "a")])
        add("Fenêtre", [("Réduire", #selector(NSWindow.miniaturize(_:)), "m"), ("Fermer", #selector(NSWindow.performClose(_:)), "w")])
        NSApp.mainMenu = main
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
