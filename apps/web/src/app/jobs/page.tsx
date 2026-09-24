import { Suspense } from "react";

import { SessionGate } from "@/components/SessionGate";
import { JobsList } from "@/components/migrator/JobsList";

export default function JobsPage() {
  return (
    <SessionGate>
      <Suspense fallback={null}>
        <JobsList />
      </Suspense>
    </SessionGate>
  );
}
