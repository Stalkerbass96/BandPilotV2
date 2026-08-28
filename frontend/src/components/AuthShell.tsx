import type { ReactNode } from "react";
import { Box, Typography } from "@mui/material";
import { CheckCircleIcon, MusicNoteIcon } from "../icons";
import { palette } from "../styles/tokens";

interface AuthShellProps { title: string; description: string; children: ReactNode; footer: ReactNode }

export default function AuthShell({ title, description, children, footer }: AuthShellProps): JSX.Element {
  return (
    <Box className="min-h-screen grid grid-cols-1 lg:grid-cols-2" sx={{ background: palette.surface }}>
      <Box className="hidden lg:flex flex-col justify-between p-12" sx={{ background: "#12151B", minHeight: "100vh", position: "relative", overflow: "hidden" }}>
        <Box sx={{ position: "absolute", width: 520, height: 520, borderRadius: "50%", border: "1px solid rgba(255,255,255,.06)", right: -220, bottom: -180 }} />
        <Box sx={{ position: "absolute", width: 360, height: 360, borderRadius: "50%", border: "1px solid rgba(232,100,45,.25)", right: -120, bottom: -100 }} />
        <Box className="flex items-center gap-3 relative">
          <Box className="flex items-center justify-center" sx={{ width: 38, height: 38, borderRadius: 2.5, background: palette.brandPrimary }}><MusicNoteIcon sx={{ color: "#fff" }} /></Box>
          <Typography sx={{ color: "#fff", fontWeight: 850, fontSize: 18 }}>BandPilot</Typography>
        </Box>
        <Box className="relative" sx={{ maxWidth: 500 }}>
          <Typography sx={{ color: "#737984", fontSize: 11, fontWeight: 800, letterSpacing: ".14em", textTransform: "uppercase" }}>From notes to performance</Typography>
          <Typography sx={{ color: "#fff", fontSize: 46, lineHeight: 1.08, fontWeight: 850, letterSpacing: "-.045em", mt: 2 }}>A score should feel good under your hands.</Typography>
          <Typography sx={{ color: "#9DA2AC", fontSize: 15, lineHeight: 1.7, mt: 3, maxWidth: 440 }}>BandPilot turns raw MIDI into practical parts with real fingerings, articulations and instrument-aware notation.</Typography>
        </Box>
        <Box className="flex gap-6 relative">
          {["Playable fingerings", "Full-band parts", "Professional exports"].map((item) => <Box key={item} className="flex items-center gap-2"><CheckCircleIcon sx={{ color: palette.brandPrimary, fontSize: 16 }} /><Typography sx={{ color: "#858B95", fontSize: 11 }}>{item}</Typography></Box>)}
        </Box>
      </Box>

      <Box className="flex items-center justify-center px-6 py-12">
        <Box sx={{ width: "100%", maxWidth: 420 }}>
          <Box className="lg:hidden flex items-center gap-2 mb-10"><Box className="flex items-center justify-center" sx={{ width: 34, height: 34, borderRadius: 2, background: palette.brandPrimary }}><MusicNoteIcon sx={{ color: "#fff", fontSize: 19 }} /></Box><Typography sx={{ fontWeight: 850 }}>BandPilot</Typography></Box>
          <Typography className="bp-eyebrow">Welcome</Typography>
          <Typography component="h1" sx={{ color: palette.textPrimary, fontSize: 34, fontWeight: 850, letterSpacing: "-.04em", mt: 1.25 }}>{title}</Typography>
          <Typography sx={{ color: palette.textSecondary, fontSize: 13.5, lineHeight: 1.6, mt: 1, mb: 4 }}>{description}</Typography>
          {children}
          <Box sx={{ mt: 3 }}>{footer}</Box>
        </Box>
      </Box>
    </Box>
  );
}
