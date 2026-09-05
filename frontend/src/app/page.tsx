"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { landingPathFor, useAuth } from "@/lib/auth";
import { Loading } from "@/components/ui";

export default function Home() {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;
    router.replace(user ? landingPathFor(user.role) : "/login");
  }, [user, loading, router]);

  return <Loading />;
}
