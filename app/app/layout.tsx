import '@fontsource/funnel-sans/400.css';
import '@fontsource/funnel-sans/500.css';
import '@fontsource/funnel-sans/700.css';
import './globals.css';
import './editorial.css';
import './backdrop.css';
import './package-viewer.css';
export const metadata={title:'Neufert Digital',description:'Biblioteca personal de arquitectura, con referencias al original.'};
export default function Layout({children}:{children:React.ReactNode}){return <html lang="es"><body>{children}</body></html>}
