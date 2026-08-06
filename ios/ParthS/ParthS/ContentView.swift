import SwiftUI

struct ContentView: View {
    @State private var biometricsPassed = false
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        ZStack {
            if biometricsPassed {
                DashboardWebView()
                    .ignoresSafeArea()
            }

            // Layered on top rather than swapped out, so returning from the
            // background re-locks instantly instead of showing a frame of
            // the dashboard first.
            if !biometricsPassed {
                BiometricGateView {
                    biometricsPassed = true
                }
            }
        }
        .onChange(of: scenePhase) { _, newPhase in
            if newPhase == .background {
                // Re-lock on backgrounding. The dashboard's own PIN/token
                // stays in sessionStorage inside the WebView — only this
                // outer biometric layer resets, so unlocking again doesn't
                // require re-entering the PIN too.
                biometricsPassed = false
            }
        }
    }
}
