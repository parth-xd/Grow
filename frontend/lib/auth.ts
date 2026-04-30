import NextAuth from "next-auth";
import GoogleProvider from "next-auth/providers/google";

export const authOptions = {
  providers: [
    GoogleProvider({
      clientId: process.env.GOOGLE_CLIENT_ID || "",
      clientSecret: process.env.GOOGLE_CLIENT_SECRET || "",
    }),
  ],
  pages: {
    signIn: "/login",
  },
  callbacks: {
    async redirect({ url, baseUrl }) {
      // After login, redirect to setup page
      if (url.startsWith(baseUrl)) {
        return `${baseUrl}/setup`;
      }
      return baseUrl + "/setup";
    },
  },
};

export default NextAuth(authOptions);
