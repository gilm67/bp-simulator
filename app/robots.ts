import type { MetadataRoute } from "next";

const BASE = "https://www.execpartners.ch";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        disallow: ["/api/", "/admin/"],
      },
    ],
    sitemap: `${BASE}/sitemap.xml`,
  };
}
