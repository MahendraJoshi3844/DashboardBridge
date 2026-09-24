import { SessionGate } from "@/components/SessionGate";
import { PowerBiWorkspace } from "@/components/migrator/PowerBiWorkspace";

export default async function PowerBiWorkspacePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <SessionGate>
      <PowerBiWorkspace projectId={id} />
    </SessionGate>
  );
}
