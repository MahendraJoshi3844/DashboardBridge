import { Suspense } from "react";

import { SessionGate } from "@/components/SessionGate";
import { JobDetail } from "@/components/migrator/JobDetail";

export default async function JobPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <SessionGate>
      <Suspense fallback={null}>
        <JobDetail projectId={id} />
      </Suspense>
    </SessionGate>
  );
}
