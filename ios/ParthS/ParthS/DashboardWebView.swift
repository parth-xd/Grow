import SwiftUI
import WebKit

/// Loads the real dashboard, unchanged — same index.html, same lock screen,
/// same 13 tabs. Nothing here duplicates that UI; this is a thin frame
/// around the existing page, matching "keep the dashboard vanilla."
///
/// The URL is a single constant, not a settings screen — one user, one Mac,
/// no configurability beyond what's actually needed right now.
enum DashboardTarget {
    // Simulator shares the Mac's own network stack, so this resolves to the
    // Mac directly with zero setup — the fastest path to seeing this run.
    // Swap to the Tailscale MagicDNS name (e.g.
    // "http://parths-mac.tailXXXX.ts.net:8000") once Tailscale is set up and
    // FLASK_HOST is 0.0.0.0, to run this on a real device away from home Wi-Fi.
    static let url = URL(string: "http://localhost:8000")!
}

struct DashboardWebView: UIViewRepresentable {
    func makeUIView(context: Context) -> WKWebView {
        let webView = WKWebView(frame: .zero)
        webView.scrollView.contentInsetAdjustmentBehavior = .never
        webView.load(URLRequest(url: DashboardTarget.url))
        return webView
    }

    func updateUIView(_ uiView: WKWebView, context: Context) {
        // Nothing to sync — the page manages its own state (PIN lock,
        // sessionStorage, tab navigation) exactly as it does in a browser.
    }
}
