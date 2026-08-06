import SwiftUI

struct ContentView: View {
    @State private var biometricsPassed = false
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        ZStack {
            // Unconditional — an earlier version gated this behind
            // `if biometricsPassed`, which made SwiftUI destroy and recreate
            // the WKWebView every time the gate re-locked. sessionStorage
            // lives inside that WKWebView's browsing context, so the PIN/
            // token this view's own comment claimed would "stay" was in fact
            // wiped on every single backgrounding, forcing a full reload and
            // a re-entered PIN each time — the opposite of the intent below.
            // Keeping the view alive and only covering it is what actually
            // preserves the session across a Face ID re-check.
            DashboardWebView()
                .ignoresSafeArea()

            if !biometricsPassed {
                BiometricGateView {
                    biometricsPassed = true
                }
            }
        }
        .onChange(of: scenePhase) { _, newPhase in
            if newPhase == .background {
                // Re-lock on backgrounding. The dashboard's own PIN/token
                // now genuinely does stay in sessionStorage inside the
                // WebView (see above) — only this outer biometric layer
                // resets, so unlocking again doesn't require re-entering
                // the PIN too.
                biometricsPassed = false
            }
        }
    }
}
