export type DisplayHealth = "BUFFERING" | "CURRENT" | "DISPLAY_DELAYED";

export interface PlaybackVector3 { x: number; y: number; z: number }
export interface PlaybackQuaternion { w: number; x: number; y: number; z: number }

export interface RawDisplaySample {
  correlationId: string;
  sequence: number;
  sourceTimestampS: number;
  sourceClockId: string;
  sourceClockEpoch: number;
  receivedMonotonicS: number;
  position: PlaybackVector3;
  truthPosition?: PlaybackVector3;
  orientation: PlaybackQuaternion;
}

export type DisplaySourceRow = Pick<
  RawDisplaySample,
  "correlationId" | "sequence" | "sourceTimestampS" | "sourceClockId" | "sourceClockEpoch"
>;

export interface RenderedDisplayState {
  sourceTimestampS: number;
  sourceClockId: string;
  sourceClockEpoch: number;
  position: PlaybackVector3;
  truthPosition?: PlaybackVector3;
  orientation: PlaybackQuaternion;
  health: DisplayHealth;
  interpolationState: "EXACT" | "INTERPOLATED" | "FROZEN";
  sourceRows: DisplaySourceRow[];
  bufferInducedEstimateDisplacementM: number;
  presentationOnly: true;
  rawEvidence: false;
}

export interface PlaybackDiagnostics {
  health: DisplayHealth;
  bufferedSamples: number;
  reorderedSamples: number;
  duplicateSamples: number;
  coalescedSamples: number;
  droppedSamples: number;
  playbackBufferAgeS: number;
}

export interface PlaybackSettings {
  playbackBufferS: number;
  maximumInterpolationGapS: number;
  maximumExtrapolationS: number;
  maximumSamples: number;
}

export const DEFAULT_PLAYBACK_SETTINGS: PlaybackSettings = {
  playbackBufferS: 0.25,
  maximumInterpolationGapS: 0.20,
  maximumExtrapolationS: 0.10,
  maximumSamples: 2_000,
};

export class SourceTimePlaybackBuffer {
  private samples: RawDisplaySample[] = [];
  private lastValid?: RenderedDisplayState;
  private health: DisplayHealth = "BUFFERING";
  private reorderedSamples = 0;
  private duplicateSamples = 0;
  private coalescedSamples = 0;
  private droppedSamples = 0;

  constructor(private readonly settings: PlaybackSettings = DEFAULT_PLAYBACK_SETTINGS) {
    if (settings.playbackBufferS < 0 || settings.maximumInterpolationGapS <= 0
      || settings.maximumExtrapolationS < 0 || settings.maximumSamples < 2) {
      throw new Error("Playback settings are outside their bounded contract");
    }
  }

  push(sample: RawDisplaySample): void {
    if (!validSample(sample)) {
      this.droppedSamples += 1;
      return;
    }
    const duplicate = this.samples.find((item) => item.correlationId === sample.correlationId
      || (item.sourceClockId === sample.sourceClockId
        && item.sourceClockEpoch === sample.sourceClockEpoch
        && item.sequence === sample.sequence));
    if (duplicate) {
      this.duplicateSamples += 1;
      return;
    }
    const latest = this.samples.at(-1);
    if (latest && compareSample(sample, latest) < 0) this.reorderedSamples += 1;
    const sameTimestampIndex = this.samples.findIndex((item) => sameEpoch(item, sample)
      && item.sourceTimestampS === sample.sourceTimestampS);
    if (sameTimestampIndex >= 0) {
      this.samples[sameTimestampIndex] = sample;
      this.coalescedSamples += 1;
    } else {
      this.samples.push(sample);
    }
    this.samples.sort(compareSample);
    if (this.samples.length > this.settings.maximumSamples) {
      const removed = this.samples.length - this.settings.maximumSamples;
      this.samples.splice(0, removed);
      this.droppedSamples += removed;
    }
  }

  render(observedMonotonicS?: number): RenderedDisplayState | undefined {
    const latest = this.samples.at(-1);
    if (!latest) return undefined;
    const epoch = this.samples.filter((sample) => sameEpoch(sample, latest));
    const receivedAgeS = observedMonotonicS === undefined
      ? 0
      : Math.max(0, observedMonotonicS - latest.receivedMonotonicS);
    const playbackAdvanceS = Math.min(receivedAgeS, this.settings.maximumExtrapolationS);
    const targetSourceS = Math.min(
      latest.sourceTimestampS,
      latest.sourceTimestampS - this.settings.playbackBufferS + playbackAdvanceS,
    );
    const before = epoch.filter((sample) => sample.sourceTimestampS <= targetSourceS).at(-1);
    const after = epoch.find((sample) => sample.sourceTimestampS >= targetSourceS);
    if (!before || !after) return this.freeze("BUFFERING");
    const gapS = after.sourceTimestampS - before.sourceTimestampS;
    if (gapS > this.settings.maximumInterpolationGapS) {
      // Refill from the first valid post-gap sample. Keeping the pre-gap side would
      // make every later target rediscover the same invalid interpolation gap.
      this.samples = epoch.filter((sample) => sample.sourceTimestampS >= after.sourceTimestampS);
      return this.freeze("DISPLAY_DELAYED");
    }
    const factor = gapS <= 0 ? 0 : (targetSourceS - before.sourceTimestampS) / gapS;
    this.health = receivedAgeS > this.settings.maximumExtrapolationS
      ? "DISPLAY_DELAYED"
      : "CURRENT";
    this.lastValid = {
      sourceTimestampS: targetSourceS,
      sourceClockId: latest.sourceClockId,
      sourceClockEpoch: latest.sourceClockEpoch,
      position: lerpVector(before.position, after.position, factor),
      truthPosition: before.truthPosition && after.truthPosition
        ? lerpVector(before.truthPosition, after.truthPosition, factor)
        : undefined,
      orientation: normalizedLerp(before.orientation, after.orientation, factor),
      health: this.health,
      interpolationState: gapS <= 0 || factor <= 0 || factor >= 1 ? "EXACT" : "INTERPOLATED",
      sourceRows: sourceRowsForRender(before, after, factor),
      bufferInducedEstimateDisplacementM: vectorDistance(
        latest.position,
        lerpVector(before.position, after.position, factor),
      ),
      presentationOnly: true,
      rawEvidence: false,
    };
    return this.lastValid;
  }

  diagnostics(): PlaybackDiagnostics {
    const latest = this.samples.at(-1);
    const rendered = this.lastValid;
    return {
      health: this.health,
      bufferedSamples: this.samples.length,
      reorderedSamples: this.reorderedSamples,
      duplicateSamples: this.duplicateSamples,
      coalescedSamples: this.coalescedSamples,
      droppedSamples: this.droppedSamples,
      playbackBufferAgeS: latest && rendered
        ? Math.max(0, latest.sourceTimestampS - rendered.sourceTimestampS)
        : 0,
    };
  }

  rawSamples(): readonly RawDisplaySample[] { return this.samples; }

  private freeze(health: DisplayHealth): RenderedDisplayState | undefined {
    this.health = health;
    return this.lastValid ? { ...this.lastValid, health, interpolationState: "FROZEN" } : undefined;
  }
}

function sourceRowsForRender(
  before: RawDisplaySample,
  after: RawDisplaySample,
  factor: number,
): DisplaySourceRow[] {
  const selected = factor <= 0 ? [before] : factor >= 1 ? [after] : [before, after];
  return selected.map((sample) => ({
    correlationId: sample.correlationId,
    sequence: sample.sequence,
    sourceTimestampS: sample.sourceTimestampS,
    sourceClockId: sample.sourceClockId,
    sourceClockEpoch: sample.sourceClockEpoch,
  }));
}

function compareSample(left: RawDisplaySample, right: RawDisplaySample): number {
  return left.sourceClockId.localeCompare(right.sourceClockId)
    || left.sourceClockEpoch - right.sourceClockEpoch
    || left.sourceTimestampS - right.sourceTimestampS
    || left.sequence - right.sequence;
}

function sameEpoch(left: RawDisplaySample, right: RawDisplaySample): boolean {
  return left.sourceClockId === right.sourceClockId
    && left.sourceClockEpoch === right.sourceClockEpoch;
}

function validSample(sample: RawDisplaySample): boolean {
  return sample.sequence >= 0
    && sample.sourceClockEpoch >= 0
    && [sample.sourceTimestampS, sample.receivedMonotonicS,
      sample.position.x, sample.position.y, sample.position.z,
      sample.orientation.w, sample.orientation.x, sample.orientation.y,
      sample.orientation.z].every(Number.isFinite);
}

function lerpVector(left: PlaybackVector3, right: PlaybackVector3, factor: number): PlaybackVector3 {
  return {
    x: left.x + (right.x - left.x) * factor,
    y: left.y + (right.y - left.y) * factor,
    z: left.z + (right.z - left.z) * factor,
  };
}

function vectorDistance(left: PlaybackVector3, right: PlaybackVector3): number {
  return Math.hypot(left.x - right.x, left.y - right.y, left.z - right.z);
}

function normalizedLerp(
  left: PlaybackQuaternion,
  right: PlaybackQuaternion,
  factor: number,
): PlaybackQuaternion {
  const sign = left.w * right.w + left.x * right.x + left.y * right.y + left.z * right.z < 0 ? -1 : 1;
  const value = {
    w: left.w + (right.w * sign - left.w) * factor,
    x: left.x + (right.x * sign - left.x) * factor,
    y: left.y + (right.y * sign - left.y) * factor,
    z: left.z + (right.z * sign - left.z) * factor,
  };
  const length = Math.hypot(value.w, value.x, value.y, value.z) || 1;
  return { w: value.w / length, x: value.x / length, y: value.y / length, z: value.z / length };
}
