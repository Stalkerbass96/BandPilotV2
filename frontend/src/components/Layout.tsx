/**
 * Layout shell — white app bar with navigation and user controls.
 *
 * Design:
 *  - Fixed-height (56px) white header with a 1px bottom divider.
 *  - Active nav link shows a 2px brand-color indicator bar underneath.
 *  - Below 768px the nav collapses into a hamburger menu.
 */

import { type ReactNode, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  Box,
  Drawer,
  IconButton,
  List,
  ListItemButton,
  ListItemText,
} from "@mui/material";
import MenuIcon from "@mui/icons-material/Menu";
import MusicNoteIcon from "@mui/icons-material/MusicNote";
import LogoutIcon from "@mui/icons-material/Logout";
import { useAuthStore } from "../store/auth";
import { palette } from "../styles/tokens";

interface LayoutProps {
  children: ReactNode;
}

interface NavItem {
  label: string;
  path: string;
}

export default function Layout({ children }: LayoutProps): JSX.Element {
  const navigate = useNavigate();
  const location = useLocation();
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const handleLogout = (): void => {
    logout();
    navigate("/login");
  };

  const navItems: NavItem[] = isAuthenticated
    ? [
        { label: "Import", path: "/" },
        { label: "BYOK", path: "/byok" },
      ]
    : [
        { label: "Login", path: "/login" },
        { label: "Register", path: "/register" },
      ];

  const isActivePath = (path: string): boolean => {
    if (path === "/") return location.pathname === "/";
    return location.pathname.startsWith(path);
  };

  return (
    <Box className="min-h-screen flex flex-col bg-surface">
      {/* ── Header (h-56px, white, bottom divider) ── */}
      <Box
        component="header"
        className="bg-canvas flex items-center px-4 sm:px-6"
        sx={{
          height: 56,
          borderBottom: `1px solid ${palette.borderDefault}`,
          position: "sticky",
          top: 0,
          zIndex: 1100,
        }}
      >
        {/* Logo */}
        <Link to="/" className="flex items-center gap-2 no-underline">
          <MusicNoteIcon sx={{ color: palette.brandPrimary, fontSize: 24 }} />
          <span
            className="text-text-primary font-bold text-lg"
            style={{ color: palette.textPrimary }}
          >
            FretPilot
          </span>
        </Link>

        {/* Desktop nav (≥768px) */}
        <Box className="hidden md:flex items-center gap-1 ml-8 h-full">
          {navItems.map((item) => {
            const active = isActivePath(item.path);
            return (
              <Link
                key={item.path}
                to={item.path}
                className="relative flex items-center px-3 no-underline"
                style={{
                  height: "100%",
                  color: active
                    ? palette.brandPrimary
                    : palette.textSecondary,
                  fontWeight: active ? 600 : 500,
                  fontSize: 14,
                }}
              >
                {item.label}
                {active && (
                  <Box
                    sx={{
                      position: "absolute",
                      bottom: 0,
                      left: 0,
                      right: 0,
                      height: 2,
                      backgroundColor: palette.brandPrimary,
                      borderTopLeftRadius: 2,
                      borderTopRightRadius: 2,
                    }}
                  />
                )}
              </Link>
            );
          })}
        </Box>

        {/* Spacer */}
        <Box className="flex-1" />

        {/* User controls (desktop) */}
        {isAuthenticated && user && (
          <Box className="hidden md:flex items-center gap-2">
            <span
              className="text-sm"
              style={{ color: palette.textSecondary }}
            >
              {user.email}
            </span>
            <IconButton
              onClick={handleLogout}
              size="small"
              title="Logout"
              sx={{ color: palette.textSecondary }}
            >
              <LogoutIcon fontSize="small" />
            </IconButton>
          </Box>
        )}

        {/* Hamburger (mobile <768px) */}
        <IconButton
          className="md:!hidden"
          onClick={() => setDrawerOpen(true)}
          sx={{ color: palette.textPrimary }}
        >
          <MenuIcon />
        </IconButton>
      </Box>

      {/* ── Mobile drawer ── */}
      <Drawer
        anchor="right"
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        PaperProps={{ sx: { width: 240, pt: 2 } }}
      >
        <List>
          {navItems.map((item) => (
            <ListItemButton
              key={item.path}
              component={Link}
              to={item.path}
              onClick={() => setDrawerOpen(false)}
              selected={isActivePath(item.path)}
            >
              <ListItemText
                primary={item.label}
                primaryTypographyProps={{ fontWeight: 500 }}
              />
            </ListItemButton>
          ))}
          {isAuthenticated && (
            <ListItemButton onClick={handleLogout}>
              <ListItemText
                primary="Logout"
                primaryTypographyProps={{
                  fontWeight: 500,
                  color: "error",
                }}
              />
            </ListItemButton>
          )}
        </List>
      </Drawer>

      {/* ── Page content ── */}
      <Box className="flex-1 w-full max-w-7xl mx-auto px-4 sm:px-6 py-6">
        {children}
      </Box>
    </Box>
  );
}
