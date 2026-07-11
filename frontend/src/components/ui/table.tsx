import * as React from 'react'

import { cn } from '@/lib/utils'

/**
 * Table primitives for the results list view. Wrap in TableScroll to get a
 * horizontally scrollable container (results tables must never break the page
 * layout — PRD §7). TableHeader supports a sticky header.
 */
function TableScroll({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('w-full overflow-x-auto', className)} {...props} />
}

function Table({ className, ...props }: React.HTMLAttributes<HTMLTableElement>) {
  return <table className={cn('w-full caption-bottom border-collapse text-sm', className)} {...props} />
}

function TableHeader({
  className,
  sticky,
  ...props
}: React.HTMLAttributes<HTMLTableSectionElement> & { sticky?: boolean }) {
  return (
    <thead
      className={cn(
        'border-b border-border text-left text-xs uppercase tracking-wide text-brand-grey',
        sticky && 'sticky top-0 z-10 bg-background',
        className,
      )}
      {...props}
    />
  )
}

function TableBody({ className, ...props }: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <tbody className={cn('[&_tr:last-child]:border-0', className)} {...props} />
}

function TableRow({ className, ...props }: React.HTMLAttributes<HTMLTableRowElement>) {
  return (
    <tr className={cn('border-b border-border transition-colors hover:bg-muted/60', className)} {...props} />
  )
}

function TableHead({ className, ...props }: React.ThHTMLAttributes<HTMLTableCellElement>) {
  return <th className={cn('h-10 px-3 font-medium align-middle whitespace-nowrap', className)} {...props} />
}

function TableCell({ className, ...props }: React.TdHTMLAttributes<HTMLTableCellElement>) {
  return <td className={cn('px-3 py-3 align-middle', className)} {...props} />
}

export { TableScroll, Table, TableHeader, TableBody, TableRow, TableHead, TableCell }
