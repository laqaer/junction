import { site } from "../data/site";

/** JSON-LD builders (site-spec §1). No aggregateRating, ever. */
export function softwareApplication() {
  return {
    "@context": "https://schema.org",
    "@type": "SoftwareApplication",
    name: site.name,
    applicationCategory: "DeveloperApplication",
    operatingSystem: "macOS, Linux",
    isAccessibleForFree: true,
    softwareVersion: site.version,
    license: "https://www.apache.org/licenses/LICENSE-2.0",
    url: site.domain + "/",
    downloadUrl: site.githubRepo,
    offers: { "@type": "Offer", price: "0", priceCurrency: "USD" },
  };
}

export function organization() {
  return {
    "@context": "https://schema.org",
    "@type": "Organization",
    name: site.company,
    url: site.domain + "/",
    logo: `${site.domain}/favicon.svg`,
    sameAs: [site.githubRepo],
  };
}

export function webSite() {
  return {
    "@context": "https://schema.org",
    "@type": "WebSite",
    name: site.name,
    url: site.domain + "/",
  };
}

export function breadcrumbList(crumbs: { label: string; href: string }[]) {
  return {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: crumbs.map((c, i) => ({
      "@type": "ListItem",
      position: i + 1,
      name: c.label,
      item: new URL(c.href, site.domain).toString(),
    })),
  };
}
