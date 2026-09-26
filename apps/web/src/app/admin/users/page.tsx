import { SessionGate } from "@/components/SessionGate";
import { UsersAdmin } from "@/components/migrator/UsersAdmin";

export default function UsersAdminPage() {
  return (
    <SessionGate>
      <UsersAdmin />
    </SessionGate>
  );
}
