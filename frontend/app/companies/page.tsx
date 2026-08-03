"use client";
import Link from "next/link";

import { useCompanies } from "@/lib/hooks";

const TYPE_KO: Record<string, string> = { core: "Core", specialist: "Specialist", dynamic: "Dynamic" };

export default function CompaniesPage() {
  const { data, isLoading } = useCompanies();
  return (
    <div>
      <h1 className="mb-4 text-xl font-semibold">기업</h1>
      {isLoading && <p className="text-sm text-slate-400">불러오는 중…</p>}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-slate-400">
            <tr>
              <th className="py-2">티커</th><th>이름</th><th>섹터</th>
              <th>구분</th><th>Signal Role</th>
            </tr>
          </thead>
          <tbody>
            {data?.companies.map((c) => (
              <tr key={c.ticker} className="border-t border-slate-100">
                <td className="py-2">
                  <Link href={`/companies/${c.ticker}`} className="font-medium text-blue-600 hover:underline">
                    {c.ticker}
                  </Link>
                </td>
                <td>{c.name}</td>
                <td className="text-slate-500">{c.sector}</td>
                <td><span className="pill">{TYPE_KO[c.universe_type ?? ""] ?? c.universe_type}</span></td>
                <td className="space-x-1">
                  {c.signal_roles.map((r) => (
                    <span key={r} className="pill">{r.replace(/_sensor$/, "")}</span>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
