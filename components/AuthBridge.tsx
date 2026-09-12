"use client";

import { useAuth } from "@clerk/nextjs";
import { useEffect } from "react";

import { setAuthTokenProvider } from "@/lib/api";

/** Hands the API client a way to get a fresh session token.
 *
 * The alternative — passing `getToken` into all forty-odd call sites — would
 * mean every new endpoint is one forgotten argument away from an anonymous
 * request. Registering once here keeps `lib/api.ts` free of React and makes
 * "is this call authenticated" a property of the client, not of the caller. */
export default function AuthBridge() {
  const { getToken, isLoaded } = useAuth();

  useEffect(() => {
    if (!isLoaded) return;
    setAuthTokenProvider(() => getToken());
    return () => setAuthTokenProvider(null);
  }, [getToken, isLoaded]);

  return null;
}
