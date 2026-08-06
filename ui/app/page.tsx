import type { Metadata } from "next";
import { ControlCenter } from "./components/ControlCenter";

export const metadata: Metadata = {
  title: { absolute: "Aerium Control — CrazySwarm" },
  description: "A truthful simulation-first mission and spatial control center for Crazyflie vehicles.",
};

export default function Home() {
  return <ControlCenter />;
}
