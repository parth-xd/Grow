import SwiftUI
import WebKit

/// Loads the real dashboard, unchanged — same index.html, same lock screen,
/// same 13 tabs. Nothing here duplicates that UI; this is a thin frame
/// around the existing page, matching "keep the dashboard vanilla."
///
/// The URL is a single constant, not a settings screen — one user, one Mac,
/// no configurability beyond what's actually needed right now.
///
/// Reached over Tailscale Serve, which proxies this HTTPS hostname to
/// 127.0.0.1:8000 on the Mac, encrypted, and only for devices signed into
/// the same tailnet. Two consequences worth knowing:
///   - Flask itself still binds to 127.0.0.1 only, so port 8000 is never
///     exposed on whatever Wi-Fi the Mac is joined to.
///   - Serve terminates TLS with a real Let's Encrypt cert for the
///     *.ts.net name, so there is NO App Transport Security exception in
///     Info.plist — nothing here needs plain HTTP.
/// Works identically on Simulator and a real device, on Wi-Fi or cellular,
/// as long as both the Mac and the phone are signed into the tailnet.
enum DashboardTarget {
    #if targetEnvironment(simulator)
    // The Simulator does NOT inherit the Mac's Tailscale DNS — MagicDNS names
    // fail to resolve there ("A server with the specified hostname could not
    // be found"), even while the same name works fine in the Mac's browser.
    // It does share the Mac's network stack, so loopback reaches Flask
    // directly and needs no tunnel. Simulator-only, so the shipped build on a
    // real device is unaffected.
    static let url = URL(string: "http://localhost:8000")!
    #else
    static let url = URL(string: "https://parths-macbook-air.tailfba767.ts.net")!
    #endif
}

private enum LoadState: Equatable {
    case loading
    case loaded
    case failed(String)
}

/// Public surface — a SwiftUI View, not a raw UIViewRepresentable, because
/// this owns the loading/error chrome around the actual web content. An
/// earlier version had no WKNavigationDelegate at all: if Flask wasn't
/// running, or the URL was wrong, the screen just stayed blank white
/// forever with no way to tell "still loading" from "broken" from "wrong
/// address." Real trading dashboard, so a silent dead end here is worse
/// than in most apps.
struct DashboardWebView: View {
    @StateObject private var model = WebViewModel()

    var body: some View {
        ZStack {
            WKWebViewRepresentable(model: model)
                .ignoresSafeArea()

            switch model.loadState {
            case .loading:
                ProgressView()
                    .controlSize(.large)
            case .loaded:
                EmptyView()
            case .failed(let message):
                VStack(spacing: 16) {
                    Text("Can't reach the dashboard")
                        .font(.headline)
                    Text(message)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, 32)
                    Button("Retry", action: model.reload)
                        .buttonStyle(.borderedProminent)
                }
                .padding(24)
                .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16))
                .padding(32)
            }
        }
    }
}

@MainActor
private final class WebViewModel: ObservableObject {
    @Published fileprivate var loadState: LoadState = .loading
    fileprivate weak var webView: WKWebView?

    func reload() {
        loadState = .loading
        webView?.load(URLRequest(url: DashboardTarget.url))
    }
}

private struct WKWebViewRepresentable: UIViewRepresentable {
    @ObservedObject var model: WebViewModel

    func makeCoordinator() -> Coordinator {
        Coordinator(model: model)
    }

    func makeUIView(context: Context) -> WKWebView {
        let webView = WKWebView(frame: .zero)
        webView.scrollView.contentInsetAdjustmentBehavior = .never
        webView.navigationDelegate = context.coordinator
        // Without a uiDelegate, WKWebView silently drops every JavaScript
        // dialog and confirm() returns false immediately. The dashboard has
        // 14 confirm() calls guarding Buy, Sell, "Close ALL open trades",
        // F&O real-money orders and Logout — so in the app every one of
        // those actions did nothing at all, with no dialog and no
        // explanation. (They failed closed, never executing unconfirmed, so
        // nothing was ever traded by accident — but nothing worked either.)
        webView.uiDelegate = context.coordinator
        model.webView = webView
        webView.load(URLRequest(url: DashboardTarget.url))
        return webView
    }

    func updateUIView(_ uiView: WKWebView, context: Context) {
        // Nothing to sync — the page manages its own state (PIN lock,
        // sessionStorage, tab navigation) exactly as it does in a browser.
    }

    final class Coordinator: NSObject, WKNavigationDelegate, WKUIDelegate {
        let model: WebViewModel
        init(model: WebViewModel) { self.model = model }

        // MARK: - JavaScript dialogs
        //
        // WKWebView has no built-in UI for alert/confirm/prompt; without
        // these three methods the calls are dropped and confirm() resolves
        // to false. Every completion handler here must be invoked exactly
        // once — WKWebView raises an exception if one is dropped or called
        // twice — so each path below either presents an alert whose every
        // button calls it, or calls it immediately on the bail-out.

        /// The topmost presented controller, so an alert still appears when
        /// something else (a sheet, another alert) is already up.
        private func presenter(for webView: WKWebView) -> UIViewController? {
            var vc = webView.window?.rootViewController
            while let presented = vc?.presentedViewController { vc = presented }
            return vc
        }

        func webView(_ webView: WKWebView,
                     runJavaScriptAlertPanelWithMessage message: String,
                     initiatedByFrame frame: WKFrameInfo,
                     completionHandler: @escaping () -> Void) {
            guard let host = presenter(for: webView) else { completionHandler(); return }
            let alert = UIAlertController(title: nil, message: message, preferredStyle: .alert)
            alert.addAction(UIAlertAction(title: "OK", style: .default) { _ in completionHandler() })
            host.present(alert, animated: true)
        }

        func webView(_ webView: WKWebView,
                     runJavaScriptConfirmPanelWithMessage message: String,
                     initiatedByFrame frame: WKFrameInfo,
                     completionHandler: @escaping (Bool) -> Void) {
            // false is the safe default everywhere it matters here: these
            // confirms guard orders and trade closures, so "couldn't ask"
            // must mean "don't do it".
            guard let host = presenter(for: webView) else { completionHandler(false); return }
            let alert = UIAlertController(title: nil, message: message, preferredStyle: .alert)
            alert.addAction(UIAlertAction(title: "Cancel", style: .cancel) { _ in completionHandler(false) })
            alert.addAction(UIAlertAction(title: "OK", style: .default) { _ in completionHandler(true) })
            host.present(alert, animated: true)
        }

        func webView(_ webView: WKWebView,
                     runJavaScriptTextInputPanelWithPrompt prompt: String,
                     defaultText: String?,
                     initiatedByFrame frame: WKFrameInfo,
                     completionHandler: @escaping (String?) -> Void) {
            guard let host = presenter(for: webView) else { completionHandler(nil); return }
            let alert = UIAlertController(title: nil, message: prompt, preferredStyle: .alert)
            alert.addTextField { $0.text = defaultText }
            alert.addAction(UIAlertAction(title: "Cancel", style: .cancel) { _ in completionHandler(nil) })
            alert.addAction(UIAlertAction(title: "OK", style: .default) { [weak alert] _ in
                completionHandler(alert?.textFields?.first?.text)
            })
            host.present(alert, animated: true)
        }

        func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
            model.loadState = .loading
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            model.loadState = .loaded
        }

        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
            model.loadState = .failed(error.localizedDescription)
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
            model.loadState = .failed(error.localizedDescription)
        }
    }
}
