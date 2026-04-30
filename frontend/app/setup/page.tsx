"use client";

import { useSession, signOut } from "next-auth/react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ContainerScroll } from "@/components/ui/container-scroll-animation";
import { LogOut } from "lucide-react";
import { InstagramLink } from "@/components/ui/instagram-link";

export default function SetupPage() {
  const { data: session, status } = useSession();
  const router = useRouter();
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (status === "unauthenticated") {
      router.push("/login");
    }
  }, [status, router]);

  const handleSetupSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setMessage("");

    try {
      // Send API credentials to your Python backend
      const response = await fetch("/api/setup", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          apiKey,
          apiSecret,
          userEmail: session?.user?.email,
        }),
      });

      if (response.ok) {
        setMessage("Setup successful! Redirecting to dashboard...");
        setTimeout(() => {
          window.location.href = "/index.html"; // Redirect to your existing dashboard
        }, 2000);
      } else {
        setMessage("Failed to save API credentials");
      }
    } catch (error) {
      setMessage("Error: " + (error instanceof Error ? error.message : "Unknown error"));
    } finally {
      setLoading(false);
    }
  };

  const handleLogout = async () => {
    await signOut({ redirect: false });
    router.push("/login");
  };

  if (status === "loading") {
    return (
      <div className="w-full h-screen bg-black flex items-center justify-center">
        <div className="text-white text-xl">Loading...</div>
      </div>
    );
  }

  return (
    <main className="w-full bg-gradient-to-b from-black via-[#0a0a0a] to-black min-h-screen overflow-hidden relative">
      {/* Instagram Link - Top Right */}
      <div className="fixed top-6 right-6 z-50">
        <InstagramLink />
      </div>
      <ContainerScroll
        titleComponent={
          <>
            <h1 className="text-4xl font-semibold text-white">
              Connect Your
              <span className="block text-4xl md:text-[6rem] font-bold mt-1 leading-none text-transparent bg-clip-text bg-gradient-to-r from-khaki-700 to-white">
                Groww Account
              </span>
            </h1>
          </>
        }
      >
        <div className="w-full h-full bg-gradient-to-br from-slate-900 to-slate-800 flex flex-col items-center justify-center p-8 md:p-16">
          <div className="max-w-md w-full space-y-8">
            <div className="text-center space-y-2">
              <h2 className="text-3xl font-bold text-white">
                Connect Your Broker
              </h2>
              <p className="text-gray-300 text-sm">
                Enter your Groww API credentials to enable automated trading
              </p>
              <p className="text-gray-400 text-xs">
                Signed in as: <span className="text-white font-semibold">{session?.user?.name || session?.user?.email}</span>
              </p>
            </div>

            <form onSubmit={handleSetupSubmit} className="space-y-5">
              <div className="space-y-2">
                <label className="block text-sm font-semibold text-white">
                  API Key
                </label>
                <input
                  type="password"
                  placeholder="Your Groww API key"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  required
                  className="w-full px-4 py-3 bg-slate-700 text-white rounded-lg border border-slate-600 focus:border-wine-900 focus:outline-none transition focus:shadow-lg focus:shadow-wine-900/30 placeholder:text-gray-500"
                />
              </div>

              <div className="space-y-2">
                <label className="block text-sm font-semibold text-white">
                  API Secret
                </label>
                <input
                  type="password"
                  placeholder="Your Groww API secret"
                  value={apiSecret}
                  onChange={(e) => setApiSecret(e.target.value)}
                  required
                  className="w-full px-4 py-3 bg-slate-700 text-white rounded-lg border border-slate-600 focus:border-wine-900 focus:outline-none transition focus:shadow-lg focus:shadow-wine-900/30 placeholder:text-gray-500"
                />
              </div>

              {message && (
                <div
                  className={`p-3 rounded-lg text-sm font-medium ${
                    message.includes("successful")
                      ? "bg-green-900/30 text-green-300 border border-green-700"
                      : "bg-red-900/30 text-red-300 border border-red-700"
                  }`}
                >
                  {message}
                </div>
              )}

              <button
                type="submit"
                disabled={loading}
                className="w-full bg-gradient-to-r from-wine-900 to-khaki-700 text-white font-semibold py-3 px-4 rounded-lg hover:from-wine-800 hover:to-khaki-600 transition duration-200 transform hover:scale-105 disabled:opacity-50 disabled:cursor-not-allowed hover:shadow-lg hover:shadow-wine-900/50"
              >
                {loading ? "Connecting..." : "Connect Account"}
              </button>

              <p className="text-center text-xs text-gray-400">
                Your credentials are encrypted and stored securely
              </p>
            </form>

            <div className="pt-4 border-t border-slate-700">
              <button
                onClick={handleLogout}
                className="w-full flex items-center justify-center gap-2 text-gray-400 hover:text-gray-200 transition py-2 text-sm"
              >
                <LogOut size={16} />
                Sign Out
              </button>
            </div>
          </div>
        </div>
      </ContainerScroll>
    </main>
  );
}
