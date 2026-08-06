// @vitest-environment node
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { describe, expect, it } from "vitest";

type VisualManifest = {
  states: string[];
  viewports: Record<string, { width: number; height: number }>;
  files: Record<string, string>;
};

const manifestUrl = new URL("./visual/baselines/manifest.json", import.meta.url);
const directoryUrl = new URL("./visual/baselines/", import.meta.url);
const manifest = JSON.parse(await readFile(manifestUrl, "utf8")) as VisualManifest;

describe("operator-state visual baselines", () => {
  it("covers every required state at desktop and narrow viewports", () => {
    expect(manifest.states).toEqual([
      "idle",
      "running",
      "fault",
      "aborted",
      "emergency",
      "completed",
      "replay",
    ]);
    expect(manifest.viewports).toEqual({
      desktop: { width: 1440, height: 1000 },
      narrow: { width: 720, height: 1000 },
    });
    expect(Object.keys(manifest.files).sort()).toEqual(
      manifest.states.flatMap((state) => [
        `${state}-desktop.jpg`,
        `${state}-narrow.jpg`,
      ]).sort(),
    );
  });

  it.each(Object.entries(manifest.files))("protects %s with its captured hash", async (filename, expectedHash) => {
    const image = await readFile(new URL(filename, directoryUrl));
    expect([...image.subarray(0, 3)]).toEqual([0xff, 0xd8, 0xff]);
    expect(createHash("sha256").update(image).digest("hex")).toBe(expectedHash);
  });
});
