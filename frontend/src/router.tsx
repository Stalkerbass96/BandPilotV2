/**
 * Application routing — React Router v6.
 *
 * Re-exports AnimatedRoutes, which wraps the route switch in Framer Motion
 * page transitions while preserving the ProtectedRoute auth guard.
 */

export { AnimatedRoutes as AppRoutes } from "./components/AnimatedRoutes";
