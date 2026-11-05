import React from 'react';
import * as Select from '@radix-ui/react-select';
import { Check, ChevronDown } from 'lucide-react';

export function Dropdown({ id, label, value, options, onChange, disabled = false }) {
  return <Select.Root disabled={disabled} value={value} onValueChange={onChange}>
    <Select.Trigger id={id} aria-label={label} className="dropdown-trigger">
      <Select.Value />
      <Select.Icon asChild><ChevronDown size={15} aria-hidden /></Select.Icon>
    </Select.Trigger>
    <Select.Portal>
      <Select.Content className="dropdown-menu" position="popper" align="start" sideOffset={7} collisionPadding={10}>
        <Select.Viewport>
          <Select.Group>
            {options.map(({ value: option, label: text }) =>
              <Select.Item key={option} value={option} className="dropdown-option">
                <Select.ItemText>{text}</Select.ItemText>
                <Select.ItemIndicator className="dropdown-check"><Check size={15} aria-hidden /></Select.ItemIndicator>
              </Select.Item>)}
          </Select.Group>
        </Select.Viewport>
      </Select.Content>
    </Select.Portal>
  </Select.Root>;
}
