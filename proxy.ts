import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";

/** Which routes a signed-out visitor may see.
 *
 * Everything not listed here requires a session. Written as an allow-list on
 * purpose: with a deny-list, a page added next month is public by accident,
 * and the mistake is invisible until someone finds the URL. */
const isPublic = createRouteMatcher([
  // The landing page, and only the landing page: "/" exactly, not "/(.*)".
  "/",
  // Legal information must be available before an account is created.
  "/legal",
  // Tells the browser where the API is, and nothing else. It has to answer
  // before a session exists, or the first thing a signed-out visitor's client
  // gets back is a sign-in redirect where it expected JSON.
  "/api/config",
  "/sign-in(.*)",
  "/sign-up(.*)",
  // Clerk's own callbacks (OAuth return, verification links).
  "/sso-callback(.*)",
]);

/** When Clerk is not configured the app runs exactly as it did before: open,
 *  and honest about it on the sign-in page. Calling clerkMiddleware without
 *  keys throws on every request, which would turn a missing env var into a
 *  totally dead app rather than an unprotected one. */
const configured = Boolean(process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY);

/** Next 16 renamed the `middleware` file convention to `proxy`; the signature
 *  and the matcher config are unchanged, and Clerk accepts either filename on
 *  Next 16+. Kept as `proxy.ts` because the deprecated `middleware.ts` path is
 *  no longer bundled by Next on Vercel — it gets executed as raw source and
 *  dies on the first `import`. */
export default configured
  ? clerkMiddleware(async (auth, request) => {
      if (isPublic(request)) return;

      // `auth.protect()` answers 404 for a signed-out visitor, which is the
      // right shape for an API route and the wrong one for a page: someone
      // opening /library while signed out was told the page did not exist,
      // with no way to sign in from there. Redirect instead, and carry the
      // URL they asked for so they land on it rather than on the library.
      const { userId, redirectToSignIn } = await auth();
      if (!userId) return redirectToSignIn({ returnBackUrl: request.url });
    })
  : () => undefined;

export const config = {
  matcher: [
    // Everything except Next internals and static files, plus API routes.
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    "/(api|trpc)(.*)",
  ],
};
