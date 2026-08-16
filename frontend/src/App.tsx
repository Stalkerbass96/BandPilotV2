import { AppRoutes } from "./router";

/**
 * Root component — routing shell only.
 * Page logic lives in src/pages/*, keeping this component thin
 * (avoids the v1 god-component anti-pattern).
 *
 * AnimatedRoutes wraps the route switch in Framer Motion transitions.
 */
export default function App() {
  return <AppRoutes />;
}
