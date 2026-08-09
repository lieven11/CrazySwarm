import { describe, expect, it } from "vitest";
import { SourceTimePlaybackBuffer, type RawDisplaySample } from "../app/lib/playback";

function sample(sequence: number, sourceTimestampS: number, x = sourceTimestampS): RawDisplaySample {
  return {
    correlationId: `sample-${sequence}`,
    sequence,
    sourceTimestampS,
    sourceClockId: "sim-clock",
    sourceClockEpoch: 1,
    receivedMonotonicS: sourceTimestampS,
    position: { x, y: 0, z: 0.3 },
    orientation: { w: 1, x: 0, y: 0, z: 0 },
  };
}

describe("source-time playback buffer", () => {
  it("interpolates only between raw samples and labels output presentation-only", () => {
    const buffer = new SourceTimePlaybackBuffer({
      playbackBufferS: 0.25,
      maximumInterpolationGapS: 0.20,
      maximumExtrapolationS: 0.10,
      maximumSamples: 20,
    });
    for (let index = 0; index <= 10; index += 1) buffer.push(sample(index, index * 0.05));
    expect(buffer.render()).toMatchObject({
      sourceTimestampS: 0.25,
      position: { x: 0.25 },
      health: "CURRENT",
      presentationOnly: true,
      rawEvidence: false,
    });
    expect(buffer.rawSamples()).toHaveLength(11);
  });

  it("freezes without a spatial jump when a source gap exceeds the bound", () => {
    const buffer = new SourceTimePlaybackBuffer({
      playbackBufferS: 0.10,
      maximumInterpolationGapS: 0.20,
      maximumExtrapolationS: 0.10,
      maximumSamples: 20,
    });
    for (let index = 0; index <= 4; index += 1) buffer.push(sample(index, index * 0.05));
    const valid = buffer.render();
    buffer.push(sample(5, 1.20, 20));
    const delayed = buffer.render();
    expect(delayed?.health).toBe("DISPLAY_DELAYED");
    expect(delayed?.position).toEqual(valid?.position);
  });

  it("retains reordered, duplicate, coalesced, and dropped diagnostics", () => {
    const buffer = new SourceTimePlaybackBuffer({
      playbackBufferS: 0.05,
      maximumInterpolationGapS: 0.20,
      maximumExtrapolationS: 0.10,
      maximumSamples: 3,
    });
    buffer.push(sample(2, 0.10));
    buffer.push(sample(1, 0.05));
    buffer.push(sample(1, 0.05));
    buffer.push({ ...sample(3, 0.10), correlationId: "coalesced" });
    buffer.push(sample(4, 0.15));
    buffer.push(sample(5, 0.20));
    expect(buffer.diagnostics()).toMatchObject({
      reorderedSamples: 1,
      duplicateSamples: 1,
      coalescedSamples: 1,
      droppedSamples: 1,
      bufferedSamples: 3,
    });
  });
});
