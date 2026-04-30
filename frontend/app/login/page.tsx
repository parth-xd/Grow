"use client";

import { signIn, useSession } from "next-auth/react";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { ContainerScroll } from "@/components/ui/container-scroll-animation";
import { Chrome } from "lucide-react";
import { InstagramLink } from "@/components/ui/instagram-link";

export default function LoginPage() {
  const { data: session } = useSession();
  const router = useRouter();

  useEffect(() => {
    if (session) {
      router.push("/setup");
    }
  }, [session, router]);

  const handleGoogleLogin = async () => {
    await signIn("google", { redirect: false });
  };

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
              Trade Smarter with
              <span className="block text-4xl md:text-[6rem] font-bold mt-1 leading-none text-transparent bg-clip-text bg-gradient-to-r from-wine-900 to-khaki-700">
                Groww AI
              </span>
            </h1>
          </>
        }
      >
        <div className="w-full h-full bg-gradient-to-br from-slate-900 to-slate-800 flex flex-col items-center justify-center p-8 md:p-16">
          <div className="max-w-md w-full space-y-8">
            <div className="text-center space-y-3">
              <h2 className="text-3xl font-bold text-white">
                Get Started
              </h2>
              <p className="text-gray-300 text-base">
                Sign in with Google to access your trading dashboard
              </p>
            </div>

            <button
              onClick={handleGoogleLogin}
              className="w-full bg-white text-wine-900 rounded-lg py-3 px-4 font-semibold flex items-center justify-center gap-3 hover:bg-gray-50 transition duration-200 transform hover:scale-105 hover:shadow-lg hover:shadow-wine-900/50"
            >
              <Chrome size={20} />
              Sign in with Google
            </button>

            <div className="relative">
              <div className="absolute inset-0 bg-gradient-to-r from-transparent via-gray-500 to-transparent h-px"></div>
              <div className="relative flex justify-center">
                <span className="px-3 bg-slate-800 text-gray-400 text-xs tracking-wide uppercase">
                  Secure & Fast
                </span>
              </div>
            </div>

            <p className="text-center text-xs text-gray-400 leading-relaxed">
              By signing in, you agree to our Terms of Service and Privacy Policy. Your data is always secure.
            </p>
          </div>
        </div>
      </ContainerScroll>
    </main>
  );
}
