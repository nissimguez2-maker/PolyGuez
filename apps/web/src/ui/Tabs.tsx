import { ReactNode } from 'react';

interface TabsProps<T extends string = string> {
  tabs: Array<{ id: T; label: string }>;
  activeTab: T;
  onTabChange: (tabId: T) => void;
  children: ReactNode;
}

export function Tabs<T extends string = string>({ tabs, activeTab, onTabChange, children }: TabsProps<T>) {
  return (
    <div>
      <div className="border-b border-zinc-800 mb-4">
        <nav className="flex space-x-1">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => onTabChange(tab.id)}
              className={`px-4 py-2 text-sm font-medium transition-colors border-b-2 ${
                activeTab === tab.id
                  ? 'border-teal-500 text-teal-400'
                  : 'border-transparent text-zinc-500 hover:text-zinc-300 hover:border-zinc-700'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </div>
      <div>{children}</div>
    </div>
  );
}

