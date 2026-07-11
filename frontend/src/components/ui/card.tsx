import * as React from 'react'

import { cn } from '@/lib/utils'

/**
 * Card — rounded-[16px] surface (Figma adapter card / env-check row / composer).
 * Default surface is the resting brand card (#fbfbfb); pass `active` for the
 * selected state (#f8f8f8 + teal-green border).
 */
function Card({
  className,
  active,
  ...props
}: React.HTMLAttributes<HTMLDivElement> & { active?: boolean }) {
  return (
    <div
      data-active={active || undefined}
      className={cn(
        'rounded-[var(--radius-card)] border border-transparent bg-brand-card text-card-foreground',
        active && 'border-brand-selected bg-brand-card-active',
        className,
      )}
      {...props}
    />
  )
}

function CardHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('flex flex-col gap-1.5 p-6', className)} {...props} />
}

function CardTitle({ className, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h3 className={cn('text-[17px] font-medium leading-6 text-foreground', className)} {...props} />
  )
}

function CardDescription({ className, ...props }: React.HTMLAttributes<HTMLParagraphElement>) {
  return <p className={cn('text-sm text-brand-muted', className)} {...props} />
}

function CardContent({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('p-6 pt-0', className)} {...props} />
}

function CardFooter({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('flex items-center p-6 pt-0', className)} {...props} />
}

export { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter }
