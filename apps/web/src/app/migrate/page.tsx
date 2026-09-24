import { Suspense } from "react";

import { SessionGate } from "@/components/SessionGate";
import { MigratePaths } from "@/components/migrator/MigratePaths";

export default function MigratePage() {
  return (
    <SessionGate>
      <Suspense fallback={null}>
        <MigratePaths />
      </Suspense>
    </SessionGate>
  );
}
