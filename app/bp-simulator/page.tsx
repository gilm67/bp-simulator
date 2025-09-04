// app/bp-simulator/page.tsx
import BpSimulatorEmbed from "@/components/BpSimulatorEmbed";

export const metadata = {
  title: "BP Simulator",
  description:
    "Business Portability / Banker Portability simulator embedded from Streamlit.",
};

export default function Page() {
  return <BpSimulatorEmbed />;
}
