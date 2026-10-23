import { Outlet } from 'react-router-dom'
import Sidebar from './Sidebar'
import { MobileTabBar, MobileTopBar } from './MobileNav'

export default function AppLayout() {
  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <div className="min-w-0 flex-1">
        <MobileTopBar />
        <main className="mx-auto w-full max-w-5xl px-4 py-8 pb-24 md:px-8 md:pb-12">
          <Outlet />
        </main>
        <MobileTabBar />
      </div>
    </div>
  )
}