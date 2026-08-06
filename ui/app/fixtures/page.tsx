import type { Metadata } from "next";
import { FixtureGallery } from "../components/FixtureGallery";

export const metadata: Metadata = { title: "Operator-state fixtures" };

export default function FixturesPage() {
  return <FixtureGallery />;
}
