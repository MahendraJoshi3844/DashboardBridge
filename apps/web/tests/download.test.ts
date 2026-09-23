import { describe, expect, it } from "vitest";

import { producedName } from "@/lib/download";

/**
 * The name the produced project is saved under when the server's own
 * `content-disposition` is unreadable — which is the normal case across an
 * origin, because a browser can only read a response header the server has
 * listed in `Access-Control-Expose-Headers`.
 */
describe("producedName", () => {
  it("keeps the workbook's name and says what the file is", () => {
    expect(producedName("Superstore.twbx")).toBe("Superstore.pbip.zip");
    expect(producedName("Superstore.twb")).toBe("Superstore.pbip.zip");
  });

  it("strips the longer Tableau extension, not one character of it", () => {
    expect(producedName("Q4.twbx")).not.toContain("x.pbip");
  });

  it("is case-insensitive about the extension", () => {
    expect(producedName("Superstore.TWBX")).toBe("Superstore.pbip.zip");
  });

  it("leaves a name that is not a Tableau file alone", () => {
    expect(producedName("report")).toBe("report.pbip.zip");
  });

  it("still produces a usable name when there is nothing to work with", () => {
    expect(producedName("")).toBe("dashboardbridge-project.pbip.zip");
    expect(producedName("   ")).toBe("dashboardbridge-project.pbip.zip");
    expect(producedName(".twbx")).toBe("dashboardbridge-project.pbip.zip");
  });
});
