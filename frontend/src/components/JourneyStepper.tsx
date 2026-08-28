import { Box, Typography } from "@mui/material";
import { CheckCircleIcon } from "../icons";
import { palette } from "../styles/tokens";

const STEPS = ["Import", "Make playable", "Export"];

export default function JourneyStepper({ activeStep }: { activeStep: 0 | 1 | 2 }): JSX.Element {
  return (
    <Box aria-label="Project progress" className="flex items-center" sx={{ maxWidth: 520 }}>
      {STEPS.map((label, index) => {
        const complete = index < activeStep;
        const active = index === activeStep;
        return (
          <Box key={label} className="flex items-center flex-1 last:flex-none">
            <Box className="flex items-center gap-2">
              <Box
                className="flex items-center justify-center"
                sx={{
                  width: 24,
                  height: 24,
                  borderRadius: "50%",
                  color: complete || active ? "#fff" : palette.textTertiary,
                  backgroundColor: complete || active ? palette.brandPrimary : palette.subtle,
                  fontSize: 11,
                  fontWeight: 800,
                }}
              >
                {complete ? <CheckCircleIcon sx={{ fontSize: 16 }} /> : index + 1}
              </Box>
              <Typography
                sx={{
                  color: active ? palette.textPrimary : palette.textTertiary,
                  fontSize: 12,
                  fontWeight: active ? 700 : 600,
                  whiteSpace: "nowrap",
                  display: { xs: active ? "block" : "none", sm: "block" },
                }}
              >
                {label}
              </Typography>
            </Box>
            {index < STEPS.length - 1 && (
              <Box sx={{ height: 1, backgroundColor: complete ? palette.brandPrimary : palette.borderDefault, mx: 2, flex: 1 }} />
            )}
          </Box>
        );
      })}
    </Box>
  );
}
