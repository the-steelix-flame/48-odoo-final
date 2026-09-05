"use client";

/**
 * `/admin` used to be a hub page of tiles.  Owner: the-steelix-flame.
 *
 * The admin screens now live directly in the top nav, so a landing page in
 * front of them is a click that buys nothing. Kept only as a redirect so old
 * links and the browser's history don't dead-end on a 404.
 */

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { Loading } from "@/components/ui";

export default function AdminIndexPage() {
  const router = useRouter();

  useEffect(() => {
    router.replace("/admin/users");
  }, [router]);

  return <Loading />;
}
