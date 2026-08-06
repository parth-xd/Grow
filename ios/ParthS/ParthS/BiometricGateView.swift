import SwiftUI
import LocalAuthentication

/// A second, OS-level gate in front of the dashboard's own PIN screen — not a
/// replacement for it. Face ID answers "is this Parth's device"; the PIN
/// (checked server-side by /api/unlock, see app.py) answers "does this
/// session hold the secret the API requires". This is the one piece of the
/// app that couldn't live in the existing HTML/JS, since no web page can
/// call into LocalAuthentication.
struct BiometricGateView: View {
    let onUnlocked: () -> Void

    @State private var status: Status = .checking
    @State private var errorMessage: String?

    private enum Status {
        case checking, failed, unavailable
    }

    var body: some View {
        ZStack {
            // Matches the dashboard's own bone-neutral lock screen so there is
            // no colour flash between this gate and the page loading behind it.
            Color(red: 0.914, green: 0.906, blue: 0.886)
                .ignoresSafeArea()

            VStack(spacing: 16) {
                switch status {
                case .checking:
                    ProgressView()
                case .failed:
                    Text("Authentication needed")
                        .font(.headline)
                    if let errorMessage {
                        Text(errorMessage)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .multilineTextAlignment(.center)
                            .padding(.horizontal, 32)
                    }
                    Button("Try Again", action: authenticate)
                        .buttonStyle(.borderedProminent)
                case .unavailable:
                    // No Face ID/passcode configured on this device — fall
                    // through to the dashboard's own PIN screen rather than
                    // blocking entry entirely.
                    ProgressView()
                }
            }
        }
        .onAppear(perform: authenticate)
    }

    private func authenticate() {
        let context = LAContext()
        var evalError: NSError?

        guard context.canEvaluatePolicy(.deviceOwnerAuthentication, error: &evalError) else {
            // No biometrics AND no passcode set up — the PIN screen is the
            // only gate available, same as it is today.
            status = .unavailable
            onUnlocked()
            return
        }

        status = .checking
        context.evaluatePolicy(
            .deviceOwnerAuthentication,
            localizedReason: "Unlock your trading dashboard"
        ) { success, error in
            DispatchQueue.main.async {
                if success {
                    onUnlocked()
                } else {
                    status = .failed
                    errorMessage = (error as? LAError)?.localizedDescription
                }
            }
        }
    }
}
