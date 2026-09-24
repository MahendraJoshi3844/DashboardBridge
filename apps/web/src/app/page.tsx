import { redirect } from "next/navigation";

/**
 * The migrator is the front door. The guided, single-screen flow that used to
 * live here is at `/classic`, unchanged.
 */
export default function Home() {
  redirect("/migrate");
}
