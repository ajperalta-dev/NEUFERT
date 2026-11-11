import type { Metadata } from 'next';
export const metadata: Metadata = { title:'Neufert Digital',description:'Biblioteca local de arquitectura con referencias de página' };
export default function RootLayout({children}:{children:React.ReactNode}) {
  return <html lang="es"><body>{children}</body></html>;
}
