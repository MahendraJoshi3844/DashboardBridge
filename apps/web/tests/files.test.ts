import { describe, expect, it } from "vitest";

import { formatBytes } from "@/lib/migrator/files";

describe("formatBytes", () => {
  it("keeps small sizes exact", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(1023)).toBe("1023 B");
  });

  it("uses one decimal from a kilobyte up", () => {
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(formatBytes(1_572_864)).toBe("1.5 MB");
    expect(formatBytes(5 * 1024 ** 3)).toBe("5.0 GB");
  });

  it("does not invent a size for nonsense", () => {
    expect(formatBytes(-1)).toBe("—");
    expect(formatBytes(Number.NaN)).toBe("—");
  });
});
