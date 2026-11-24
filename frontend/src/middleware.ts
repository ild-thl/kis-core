import createMiddleware from "next-intl/middleware";
import { routing } from "./i18n/routing";

export default createMiddleware(routing);

export const config = {
  // Match all pathnames except for backend rewrites, API routes, internals, and static files.
  matcher: [
    "/((?!api|auth|health|docs|redoc|openapi|translate|trpc|_next|_vercel|.*\\..*).*)",
  ],
};
