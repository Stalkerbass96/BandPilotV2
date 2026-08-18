/**
 * AnimatedRoutes — wraps React Router v6 <Routes> in Framer Motion transitions.
 *
 * Each route fades + slides up (opacity 0→1, y 8→0) over 0.2s.
 * AnimatePresence with mode="wait" ensures the exiting page finishes
 * animating before the entering page begins.
 */

import { Routes, Route, Navigate, useLocation } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import type { JSX } from "react";
import LoginPage from "../pages/LoginPage";
import RegisterPage from "../pages/RegisterPage";
import ByokPage from "../pages/ByokPage";
import ImportPage from "../pages/ImportPage";
import LearningPage from "../pages/LearningPage";
import WorkbenchPage from "../pages/WorkbenchPage";
import ExportPage from "../pages/ExportPage";
import Layout from "../components/Layout";
import { useAuthStore } from "../store/auth";

const pageVariants = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -8 },
};

const pageTransition = { duration: 0.2, ease: "easeOut" };

function PageWrapper({ children }: { children: JSX.Element }): JSX.Element {
  return (
    <motion.div
      variants={pageVariants}
      initial="initial"
      animate="animate"
      exit="exit"
      transition={pageTransition}
    >
      {children}
    </motion.div>
  );
}

function ProtectedRoute({ children }: { children: JSX.Element }): JSX.Element {
  const token = useAuthStore((s) => s.token);
  if (!token) {
    return <Navigate to="/login" replace />;
  }
  return <Layout>{children}</Layout>;
}

export function AnimatedRoutes(): JSX.Element {
  const location = useLocation();

  return (
    <AnimatePresence mode="wait">
      <Routes location={location} key={location.pathname}>
        <Route
          path="/login"
          element={
            <PageWrapper>
              <LoginPage />
            </PageWrapper>
          }
        />
        <Route
          path="/register"
          element={
            <PageWrapper>
              <RegisterPage />
            </PageWrapper>
          }
        />
        <Route
          path="/byok"
          element={
            <ProtectedRoute>
              <PageWrapper>
                <ByokPage />
              </PageWrapper>
            </ProtectedRoute>
          }
        />
        <Route
          path="/learning"
          element={
            <ProtectedRoute>
              <PageWrapper>
                <LearningPage />
              </PageWrapper>
            </ProtectedRoute>
          }
        />
        <Route
          path="/"
          element={
            <ProtectedRoute>
              <PageWrapper>
                <ImportPage />
              </PageWrapper>
            </ProtectedRoute>
          }
        />
        <Route
          path="/projects/:id"
          element={
            <ProtectedRoute>
              <PageWrapper>
                <WorkbenchPage />
              </PageWrapper>
            </ProtectedRoute>
          }
        />
        <Route
          path="/projects/:id/export"
          element={
            <ProtectedRoute>
              <PageWrapper>
                <ExportPage />
              </PageWrapper>
            </ProtectedRoute>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AnimatePresence>
  );
}
