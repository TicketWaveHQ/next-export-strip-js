const structuredData = {
  '@context': 'https://schema.org',
  '@type': 'WebSite',
  name: 'Fixture site',
};

export default function Home() {
  return (
    <main>
      <h1>Home</h1>
      <p>Every page here is complete HTML and CSS.</p>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(structuredData) }} />
    </main>
  );
}
