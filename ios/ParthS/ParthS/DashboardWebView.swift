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
    static let url = URL(string: "https://parths-macbook-air.tailfba767.ts.net")!
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
        model.webView = webView
        webView.load(URLRequest(url: DashboardTarget.url))
        return webView
    }

    func updateUIView(_ uiView: WKWebView, context: Context) {
        // Nothing to sync — the page manages its own state (PIN lock,
        // sessionStorage, tab navigation) exactly as it does in a browser.
    }

    final class Coordinator: NSObject, WKNavigationDelegate {
        let model: WebViewModel
        init(model: WebViewModel) { self.model = model }

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
